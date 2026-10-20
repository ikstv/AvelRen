"""Приватний Linux lease, durable intent та обмежені локальні процеси.

Docker CLI termination is not remote job termination: the coordinator's recovery
adapter must cancel and verify its exact named Docker jobs before returning True.
"""

import argparse
import ctypes
import fcntl
import importlib.util
import json
import math
import os
import re
import select
import signal
import stat
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

LOCK_NAME = "operator-backup.lock"
STATE_NAME = "paired-backup-state.json"
PHASES = {
    "prepared",
    "on_intent",
    "paused",
    "copied",
    "off_intent",
    "resumed",
    "published",
    "failed",
    "recovery_required",
}
TERMINAL = {"resumed", "published"}
OPERATOR_CLEANUP_GRACE_SECONDS = 120.0
_authorities = {}


class BackupAuthority:
    """Process-local capability; only a live backup_lock context registers it."""

    def __init__(self, state_dir, fd, directory_fd):
        self.state_dir = state_dir
        self.fd = fd
        self.directory_fd = directory_fd
        self.owner = process_identity(os.getpid())


def process_identity(pid: int) -> dict:
    text = Path(f"/proc/{pid}/stat").read_text()
    fields = text.rsplit(")", 1)[1].split()
    return {
        "pid": pid,
        "start_ticks": int(fields[19]),
        "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
    }


def _private(info, *, directory=False):
    if (
        not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
        or info.st_uid != 0
        or info.st_mode & 0o077
        or (not directory and info.st_nlink != 1)
    ):
        raise ValueError("unsafe_backup_path")


def _directory(state_dir):
    if sys.platform != "linux" or os.geteuid() != 0:
        raise ValueError("root_linux_required")
    state_dir = Path(state_dir)
    if not state_dir.is_absolute() or any(p.is_symlink() for p in (state_dir, *state_dir.parents)):
        raise ValueError("unsafe_backup_path")
    fd = os.open(state_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        _private(os.fstat(fd), directory=True)
    except BaseException:
        os.close(fd)
        raise
    return fd


@contextmanager
def backup_lock(state_dir: Path):
    directory_fd = _directory(state_dir)
    fd = None
    authority = None
    try:
        fd = os.open(
            LOCK_NAME,
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=directory_fd,
        )
        _private(os.fstat(fd))
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("backup_busy") from None
        authority = BackupAuthority(Path(state_dir), fd, directory_fd)
        _authorities[id(authority)] = authority
        yield authority
    finally:
        if authority is not None:
            _authorities.pop(id(authority), None)
        if fd is not None:
            # Do not LOCK_UN: a supervisor may still hold this open description.
            os.close(fd)
        os.close(directory_fd)


def validate_authority(authority: BackupAuthority, state_dir: Path) -> None:
    if (
        type(authority) is not BackupAuthority
        or _authorities.get(id(authority)) is not authority
        or authority.state_dir != Path(state_dir)
        or authority.owner != process_identity(os.getpid())
    ):
        raise ValueError("invalid_backup_authority")
    fd = _directory(state_dir)
    try:
        current = os.fstat(fd)
        held = os.fstat(authority.directory_fd)
        lock = os.stat(LOCK_NAME, dir_fd=fd, follow_symlinks=False)
        _private(lock)
        owned = os.fstat(authority.fd)
        if (current.st_dev, current.st_ino) != (held.st_dev, held.st_ino) or (
            lock.st_dev,
            lock.st_ino,
        ) != (owned.st_dev, owned.st_ino):
            raise ValueError("backup_path_changed")
        _validate_held_flock(authority.fd, fd)
    finally:
        os.close(fd)


def _authority(state_dir):
    for authority in _authorities.values():
        if authority.state_dir == Path(state_dir):
            validate_authority(authority, state_dir)
            return authority
    raise ValueError("backup_lease_required")


def _token(value):
    if (
        not isinstance(value, dict)
        or set(value) != {"pid", "start_ticks", "boot_id"}
        or type(value["pid"]) is not int
        or value["pid"] <= 0
        or type(value["start_ticks"]) is not int
        or value["start_ticks"] <= 0
    ):
        raise ValueError("invalid_backup_state")
    uuid.UUID(value["boot_id"])


def _validate(value):
    fields = {
        "format_version",
        "generation",
        "owner",
        "identity",
        "phase",
        "created_at",
        "updated_at",
        "initial_capture_only",
        "children",
    }
    if not isinstance(value, dict) or set(value) not in (fields, fields | {"failure_reason"}):
        raise ValueError("invalid_backup_state")
    if (
        type(value["format_version"]) is not int
        or value["format_version"] != 1
        or value["phase"] not in PHASES
    ):
        raise ValueError("invalid_backup_state")
    uuid.UUID(value["generation"])
    _token(value["owner"])
    ident = value["identity"]
    if (
        not isinstance(ident, dict)
        or set(ident)
        != {
            "container_id",
            "image_id",
            "source_commit",
            "restart_count",
            "started_at",
            "volume",
            "network",
        }
        or not re.fullmatch(r"[0-9a-f]{64}", ident["container_id"])
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", ident["image_id"])
        or not re.fullmatch(r"[0-9a-f]{40}", ident["source_commit"])
        or type(ident["restart_count"]) is not int
        or ident["restart_count"] < 0
        or not re.fullmatch(r"[0-9TZ:.+-]{1,64}", ident["started_at"])
        or any(not re.fullmatch(r"[a-zA-Z0-9_.-]{1,128}", ident[k]) for k in ("volume", "network"))
    ):
        raise ValueError("invalid_backup_state")
    if (
        type(value["initial_capture_only"]) is not bool
        or not isinstance(value["children"], list)
        or any(
            type(value[k]) not in (int, float) or not math.isfinite(value[k]) or value[k] < 0
            for k in ("created_at", "updated_at")
        )
    ):
        raise ValueError("invalid_backup_state")
    for child in value["children"]:
        _token(child)
    if "failure_reason" in value and value["failure_reason"] not in {
        "ownership_unproven",
        "identity_changed",
        "children_unresolved",
        "off_unacknowledged",
        "recovery_failed",
        "network_failed",
        "copy_failed",
        "cancelled",
    }:
        raise ValueError("invalid_backup_state")


def read_state(state_dir: Path) -> dict | None:
    directory_fd = _directory(state_dir)
    try:
        try:
            fd = os.open(
                STATE_NAME,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                dir_fd=directory_fd,
            )
        except FileNotFoundError:
            return None
        with os.fdopen(fd) as stream:
            _private(os.fstat(stream.fileno()))
            data = stream.read(65537)
        if len(data) > 65536:
            raise ValueError("invalid_backup_state")
        value = json.loads(data)
        _validate(value)
        return value
    except (KeyError, TypeError, AttributeError):
        raise ValueError("invalid_backup_state") from None
    finally:
        os.close(directory_fd)


def write_state(state_dir: Path, value: dict) -> None:
    authority = _authority(state_dir)
    _validate(value)
    data = json.dumps(value, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(data) > 65536:
        raise ValueError("invalid_backup_state")
    # Validate an existing target before replacing it (symlink/hardlink/owner).
    try:
        _private(os.stat(STATE_NAME, dir_fd=authority.directory_fd, follow_symlinks=False))
    except FileNotFoundError:
        pass
    temporary = ".paired-state-" + uuid.uuid4().hex
    fd = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=authority.directory_fd,
    )
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(
            temporary,
            STATE_NAME,
            src_dir_fd=authority.directory_fd,
            dst_dir_fd=authority.directory_fd,
        )
        os.fsync(authority.directory_fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=authority.directory_fd)
        except FileNotFoundError:
            pass


def assert_no_handoff(state_dir):
    """A staged/crashed operator handoff blocks every ordinary coordinator."""
    directory_fd = _directory(state_dir)
    try:
        try:
            fd = os.open('collector-handoff.json', os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                         dir_fd=directory_fd)
        except FileNotFoundError:
            return
        with os.fdopen(fd) as stream:
            _private(os.fstat(stream.fileno()))
            data = stream.read(131073)
        value = json.loads(data)
        if (len(data) > 131072 or not isinstance(value, dict)
                or value.get('format_version') != 1 or value.get('phase') not in {'complete', 'rolled_back'}):
            raise ValueError('collector_handoff_required')
    finally:
        os.close(directory_fd)


def _assert_resolved(state_dir):
    assert_no_handoff(state_dir)
    value = read_state(state_dir)
    if value is not None and value["phase"] not in TERMINAL:
        raise ValueError("backup_recovery_required")


@contextmanager
def operator_guard(state_dir: Path):
    with backup_lock(state_dir) as authority:
        _assert_resolved(state_dir)
        yield authority


def assert_no_backup(state_dir: Path) -> None:
    with operator_guard(state_dir):
        pass


def _children(pid):
    try:
        return [
            int(value) for value in Path(f"/proc/{pid}/task/{pid}/children").read_text().split()
        ]
    except FileNotFoundError:
        return []


def _descendants(pid):
    result = []
    for child in _children(pid):
        result.extend(_descendants(child))
        result.append(child)
    return result


def require_process_supervision() -> None:
    """Call in coordinator preflight before capture-only on."""
    fd = None
    try:
        if sys.platform != "linux":
            raise ValueError("process_supervision_unavailable")
        fd = os.pidfd_open(os.getpid())
        signal.pidfd_send_signal(fd, 0)
        enabled = ctypes.c_int()
        if ctypes.CDLL(None, use_errno=True).prctl(37, ctypes.byref(enabled), 0, 0, 0) != 0:
            raise ValueError("process_supervision_unavailable")
    except (OSError, AttributeError):
        raise ValueError("process_supervision_unavailable") from None
    finally:
        if fd is not None:
            os.close(fd)


def _is_descendant(pid):
    visited = set()
    while pid != os.getpid():
        if pid <= 1 or pid in visited:
            return False
        visited.add(pid)
        try:
            fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        except FileNotFoundError:
            return False
        pid = int(fields[1])
    return True


def _signal_descendant(pid, sig):
    fd = None
    try:
        fd = os.pidfd_open(pid)
        if _is_descendant(pid):
            signal.pidfd_send_signal(fd, sig)
    except ProcessLookupError:
        pass
    finally:
        if fd is not None:
            os.close(fd)


def _graceful_operator_cancel(process, sig, grace_seconds):
    # Signal only the snapshot that was running when cancellation began. The
    # shell's EXIT cleanup may start new stop/verification children; do not
    # interrupt them again during this bounded grace period.
    for pid in _descendants(os.getpid()):
        _signal_descendant(pid, sig)
    until = time.monotonic() + grace_seconds
    while process.poll() is None and time.monotonic() < until:
        time.sleep(min(0.01, max(0, until - time.monotonic())))


def _terminate_and_reap():
    # A subreaper adopts escaped/double-forked grandchildren. Keep the lease until
    # every descendant is reaped, including children that call setsid().
    while True:
        descendants = _descendants(os.getpid())
        for pid in descendants:
            _signal_descendant(pid, signal.SIGKILL)
        while True:
            try:
                child, _ = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                return
            if child == 0:
                break
        time.sleep(0.01)


def _supervise(
    argv,
    deadline,
    env,
    stdout_fd,
    alive_fd,
    result_fd,
    inherited_fds,
    inherit_output,
    cleanup_grace_seconds,
):
    process = None
    cancelled = [None]
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda signum, *_: cancelled.__setitem__(0, signum))
    try:
        if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
            raise ValueError("supervisor_unavailable")
        output = (
            os.fdopen(stdout_fd, "wb")
            if stdout_fd is not None
            else (None if inherit_output else subprocess.DEVNULL)
        )
        try:
            process = subprocess.Popen(
                argv,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=None if inherit_output else subprocess.DEVNULL,
                # The private shell wrapper preserves /dev/tty confirmation.
                # Generic bounded helpers always get their own session/group.
                start_new_session=not inherit_output,
                pass_fds=inherited_fds,
            )
            result = {"returncode": None, "reason": None}
            cancellation_signal = signal.SIGTERM
            while True:
                if cancelled[0]:
                    cancellation_signal = cancelled[0]
                    result["reason"] = "command_cancelled"
                    break
                if select.select([alive_fd], [], [], 0)[0]:
                    data = os.read(alive_fd, 1)
                    # EOF after parent SIGKILL receives best-effort TERM cleanup.
                    cancellation_signal = data[0] if data else signal.SIGTERM
                    result["reason"] = "command_cancelled"
                    break
                if time.monotonic() >= deadline:
                    result["reason"] = "command_timeout"
                    break
                code = process.poll()
                if code is not None:
                    result["returncode"] = code
                    break
                time.sleep(0.01)
            if inherit_output and result["reason"]:
                _graceful_operator_cancel(process, cancellation_signal, cleanup_grace_seconds)
            _terminate_and_reap()
        finally:
            if stdout_fd is not None:
                output.close()
        os.write(result_fd, json.dumps(result).encode())
    except BaseException:
        if process is not None:
            _terminate_and_reap()
        try:
            os.write(result_fd, b'{"reason":"command_unavailable","returncode":null}')
        except OSError:
            pass
    finally:
        os._exit(0)


def run_bounded(
    argv: list[str], *, deadline: float, env: dict | None = None, stdout_path: Path | None = None
) -> int:
    return _run_bounded(argv, deadline=deadline, env=env, stdout_path=stdout_path)


def _run_bounded(
    argv,
    *,
    deadline,
    env=None,
    stdout_path=None,
    inherit_output=False,
    cleanup_grace_seconds=OPERATOR_CLEANUP_GRACE_SECONDS,
):
    if sys.platform != "linux" or not argv or not math.isfinite(deadline):
        raise ValueError("invalid_bounded_command")
    if deadline <= time.monotonic():
        raise ValueError("command_timeout")
    if not math.isfinite(cleanup_grace_seconds) or cleanup_grace_seconds < 0:
        raise ValueError("invalid_cleanup_grace")
    require_process_supervision()
    stdout_fd = None
    if stdout_path is not None:
        directory_fd = _directory(Path(stdout_path).parent)
        try:
            stdout_fd = os.open(
                Path(stdout_path).name,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory_fd,
            )
        finally:
            os.close(directory_fd)
    alive_read, alive_write = os.pipe()
    result_read, result_write = os.pipe()
    saved = {}
    pid = None
    cancellation_signal = [signal.SIGTERM]
    try:

        def interrupted(signum, *_):
            cancellation_signal[0] = signum
            raise KeyboardInterrupt

        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            saved[sig] = signal.signal(sig, interrupted)
        inherited = tuple(a.fd for a in _authorities.values())
        pid = os.fork()
        if pid == 0:
            os.close(alive_write)
            os.close(result_read)
            _supervise(
                argv,
                deadline,
                env,
                stdout_fd,
                alive_read,
                result_write,
                inherited,
                inherit_output,
                cleanup_grace_seconds,
            )
        if stdout_fd is not None:
            os.close(stdout_fd)
            stdout_fd = None
        os.close(alive_read)
        alive_read = None
        os.close(result_write)
        result_write = None
        chunks = []
        while True:
            data = os.read(result_read, 4096)
            if not data:
                break
            chunks.append(data)
        os.waitpid(pid, 0)
        pid = None
        value = json.loads(b"".join(chunks))
        if value["reason"]:
            raise ValueError(value["reason"])
        return value["returncode"]
    finally:
        # EOF tells the supervisor to cancel. Ignore repeated termination while
        # waiting: returning early would release authority before cleanup.
        for sig in saved:
            signal.signal(sig, signal.SIG_IGN)
        if pid is not None:
            try:
                os.write(alive_write, bytes([cancellation_signal[0]]))
            except BrokenPipeError:
                pass
        os.close(alive_write)
        if pid is not None:
            os.waitpid(pid, 0)
        for fd in (alive_read, result_read, result_write, stdout_fd):
            if fd is not None:
                os.close(fd)
        for sig, handler in saved.items():
            signal.signal(sig, handler)


def _owner_dead(owner):
    if owner["boot_id"] != process_identity(os.getpid())["boot_id"]:
        return False
    try:
        process_identity(owner["pid"])
    except FileNotFoundError:
        return True
    # Live PID, reused PID, zombie or different start-time all remain unresolved.
    return False


def recover_owned_run(state_dir: Path, *, runtime: object) -> dict:
    authority = _authority(state_dir)
    assert_no_handoff(state_dir)
    value = read_state(state_dir)
    if value is None:
        return {"status": "no_backup_state"}
    if value["phase"] in TERMINAL:
        return value

    def assert_owned():
        validate_authority(authority, state_dir)
        if read_state(state_dir) != value:
            raise ValueError("ownership_unproven")

    def save(**changes):
        nonlocal value
        assert_owned()
        replacement = dict(value, **changes, updated_at=time.time())
        write_state(state_dir, replacement)
        value = replacement
        return value

    def unresolved(reason):
        return save(phase="recovery_required", failure_reason=reason)

    assert_owned()
    if (
        not _owner_dead(value["owner"])
        or value["initial_capture_only"]
        or value["phase"] in {"failed", "recovery_required"}
    ):
        return unresolved("ownership_unproven")
    try:
        if runtime.identity() != value["identity"]:
            return unresolved("identity_changed")
        assert_owned()
        if runtime.cancel_children(value["children"]) is not True:
            return unresolved("children_unresolved")
        # Re-read generation and identity after cleanup; no takeover by boolean.
        assert_owned()
        if runtime.identity() != value["identity"]:
            return unresolved("identity_changed")
        mode = runtime.capture_status()
        assert_owned()
        if value["phase"] == "prepared":
            if mode.get("capture_only") is not False or mode.get("mode_ack") is not False:
                return unresolved("ownership_unproven")
        elif mode.get("capture_only") is True:
            save(phase="off_intent")
            mode = runtime.capture_only("off", authority)
        assert_owned()
        if mode.get("capture_only") is not False or mode.get("mode_ack") is not False:
            return unresolved("off_unacknowledged")
        if runtime.identity() != value["identity"]:
            return unresolved("identity_changed")
        save(phase="resumed", children=[])
        if "failure_reason" in value:
            assert_owned()
            replacement = dict(value)
            replacement.pop("failure_reason")
            write_state(state_dir, replacement)
            value = replacement
        return value
    except (ValueError, OSError, KeyError, TypeError):
        return unresolved("recovery_failed")


def _manifest_state(path):
    spec = importlib.util.spec_from_file_location(
        "guard_runtime", Path(__file__).with_name("collector-runtime-preflight.py")
    )
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    return Path(runtime.load_manifest(path)["state_dir"])


def _validate_held_flock(fd, directory_fd):
    probe = os.open(LOCK_NAME, os.O_RDWR | os.O_NOFOLLOW, dir_fd=directory_fd)
    try:
        try:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            pass
        else:
            raise ValueError("invalid_backup_authority")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(probe)


def validate_inherited_fd(state_dir: Path, fd: int, owner: dict):
    """Shell-only inherited operator authority, never a controller capability."""
    directory_fd = _directory(state_dir)
    try:
        _token(owner)
        if process_identity(owner["pid"]) != owner:
            raise ValueError("invalid_inherited_authority")
        owner_stat = Path(f"/proc/{owner['pid']}/stat").read_text().rsplit(")", 1)[1].split()
        if owner_stat[0] == "Z":
            raise ValueError("invalid_inherited_authority")
        owned = os.fstat(fd)
        _private(owned)
        expected = os.stat(LOCK_NAME, dir_fd=directory_fd, follow_symlinks=False)
        if (owned.st_dev, owned.st_ino) != (expected.st_dev, expected.st_ino):
            raise ValueError("invalid_inherited_authority")
        # This descriptor must already own the flock: another open description
        # must fail, and the inherited description itself must succeed.
        _validate_held_flock(fd, directory_fd)
        _assert_resolved(state_dir)
    finally:
        os.close(directory_fd)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["operator", "validate-inherited"])
    parser.add_argument(
        "--manifest", type=Path, default=Path("/etc/avelren/collector-runtime.json")
    )
    parser.add_argument("--fd", type=int)
    parser.add_argument("--owner")
    parser.add_argument("argv", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        directory = _manifest_state(args.manifest)
        if args.command == "validate-inherited":
            validate_inherited_fd(directory, args.fd, json.loads(args.owner))
            return 0
        argv = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
        if not argv:
            raise ValueError("operator_command_required")
        with operator_guard(directory) as authority:
            env = dict(
                os.environ,
                AVELREN_OPERATOR_GUARD_FD=str(authority.fd),
                AVELREN_OPERATOR_GUARD_OWNER=json.dumps(authority.owner),
            )
            # Shell operations keep their existing per-operation limits. The
            # supervisor adds cancellation/lifetime containment, not a new limit.
            return _run_bounded(
                argv, deadline=time.monotonic() + 86400, env=env, inherit_output=True
            )
    except (ValueError, OSError, TypeError, KeyError, ImportError):
        print("DENIED: paired backup operator guard", file=sys.stderr)
        return 75
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
