"""Linux-контракти lease, durable recovery та справжніх дочірніх процесів."""

import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

PATH = Path(__file__).with_name("paired_backup_state.py")
if PATH.exists():
    spec = importlib.util.spec_from_file_location("paired_backup_state", PATH)
    state = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = state
    spec.loader.exec_module(state)
else:
    state = None

IDENTITY = {
    "container_id": "a" * 64,
    "image_id": "sha256:" + "b" * 64,
    "source_commit": "c" * 40,
    "restart_count": 0,
    "started_at": "2026-10-13T00:00:00Z",
    "volume": "avelren-runtime-test-volume",
    "network": "avelren-runtime-test-network",
}


def record(phase="on_intent"):
    return {
        "format_version": 1,
        "generation": "11111111-1111-4111-8111-111111111111",
        "owner": {
            "pid": 2147483647,
            "start_ticks": 123,
            "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        },
        "identity": dict(IDENTITY),
        "phase": phase,
        "created_at": 1.0,
        "updated_at": 2.0,
        "initial_capture_only": False,
        "children": [],
    }


class Runtime:
    def __init__(self):
        self.current = dict(IDENTITY)
        self.paused = True
        self.events = []
        self.fail_off = False

    def identity(self):
        return self.current

    def capture_status(self):
        return {"capture_only": self.paused, "mode_ack": self.paused}

    def cancel_children(self, children):
        self.events.append("children_stopped")
        return True

    def capture_only(self, mode, authority):
        state.validate_authority(authority, authority.state_dir)
        self.events.append(mode)
        if self.fail_off:
            raise ValueError("secret sentinel")
        self.paused = mode == "on"
        return self.capture_status()


@unittest.skipUnless(sys.platform == "linux", "Linux /proc/flock proof")
class StateContract(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(state, "shared lease/recovery module is missing")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)

    def test_simultaneous_lock_and_expired_authority(self):
        with state.backup_lock(self.directory) as authority:
            with self.assertRaisesRegex(ValueError, "backup_busy"):
                with state.backup_lock(self.directory):
                    self.fail("overlapping owner admitted")
            state.validate_authority(authority, self.directory)
        with self.assertRaises(ValueError):
            state.validate_authority(authority, self.directory)

    def test_lost_flock_invalidates_internal_authority(self):
        import fcntl

        with state.backup_lock(self.directory) as authority:
            fcntl.flock(authority.fd, fcntl.LOCK_UN)
            with self.assertRaises(ValueError):
                state.validate_authority(authority, self.directory)

    def test_unsafe_lock_paths(self):
        lock = self.directory / "operator-backup.lock"
        target = self.directory / "target"
        target.touch(mode=0o600)
        for kind in ("symlink", "hardlink", "foreign", "public"):
            with self.subTest(kind=kind):
                if kind == "symlink":
                    lock.symlink_to(target)
                elif kind == "hardlink":
                    os.link(target, lock)
                else:
                    lock.touch(mode=0o600)
                    if kind == "foreign":
                        os.chown(lock, 10001, 10001)
                    else:
                        lock.chmod(0o644)
                with self.assertRaises((ValueError, OSError)):
                    with state.backup_lock(self.directory):
                        self.fail("unsafe lock admitted")
                lock.unlink()

    def test_state_atomic_interruption_and_private_mode(self):
        with state.backup_lock(self.directory):
            state.write_state(self.directory, record("prepared"))
            with patch.object(state.os, "replace", side_effect=OSError("interrupted")):
                with self.assertRaises(OSError):
                    state.write_state(self.directory, record("paused"))
            self.assertEqual(state.read_state(self.directory)["phase"], "prepared")
            self.assertEqual(
                (self.directory / "paired-backup-state.json").stat().st_mode & 0o777, 0o600
            )
            self.assertFalse(list(self.directory.glob(".paired-state-*")))

    def test_unresolved_state_blocks_and_terminal_allows(self):
        for phase in (
            "prepared",
            "on_intent",
            "paused",
            "copied",
            "off_intent",
            "failed",
            "recovery_required",
        ):
            with state.backup_lock(self.directory):
                state.write_state(self.directory, record(phase))
            with self.assertRaises(ValueError):
                state.assert_no_backup(self.directory)
        for phase in ("resumed", "published"):
            with state.backup_lock(self.directory):
                state.write_state(self.directory, record(phase))
            state.assert_no_backup(self.directory)

    def test_corrupt_and_secret_state_rejected(self):
        with state.backup_lock(self.directory):
            value = record()
            value["password"] = "sentinel"
            with self.assertRaises(ValueError):
                state.write_state(self.directory, value)
        path = self.directory / "paired-backup-state.json"
        path.write_text('{"format_version":1}')
        path.chmod(0o600)
        with self.assertRaises(ValueError):
            state.assert_no_backup(self.directory)

    def test_fifo_state_rejected_without_blocking(self):
        os.mkfifo(self.directory / "paired-backup-state.json", 0o600)
        code = (
            "import sys; from pathlib import Path; "
            f"sys.path.insert(0,{str(PATH.parent)!r}); import paired_backup_state as s; "
            f"s.read_state(Path({str(self.directory)!r}))"
        )
        try:
            result = subprocess.run([sys.executable, "-c", code], capture_output=True, timeout=0.5)
        except subprocess.TimeoutExpired:
            self.fail("unsafe FIFO state blocks recovery indefinitely")
        self.assertNotEqual(result.returncode, 0)

    def test_terminal_network_failure_does_not_block_operators(self):
        value = record("resumed")
        value["failure_reason"] = "network_failed"
        with state.backup_lock(self.directory):
            try:
                state.write_state(self.directory, value)
            except ValueError:
                self.fail("resolved upload failure category is rejected")
        state.assert_no_backup(self.directory)

    def test_oversized_state_rejected_before_overwriting_valid_state(self):
        with state.backup_lock(self.directory):
            state.write_state(self.directory, record("prepared"))
            value = record("paused")
            value["children"] = [dict(value["owner"]) for _ in range(1000)]
            with self.assertRaises(ValueError):
                state.write_state(self.directory, value)
            self.assertEqual(state.read_state(self.directory)["phase"], "prepared")

    def recover(self, value, runtime=None):
        runtime = runtime or Runtime()
        with state.backup_lock(self.directory):
            state.write_state(self.directory, value)
            result = state.recover_owned_run(self.directory, runtime=runtime)
        return result, runtime

    def test_timeout_intent_recovers_before_off(self):
        result, runtime = self.recover(record())
        self.assertEqual(runtime.events, ["children_stopped", "off"])
        self.assertEqual(result["phase"], "resumed")

    def test_already_off_still_cancels_children(self):
        runtime = Runtime()
        runtime.paused = False
        result, runtime = self.recover(record(), runtime)
        self.assertEqual(runtime.events, ["children_stopped"])
        self.assertEqual(result["phase"], "resumed")

    def test_initially_paused_never_toggled(self):
        value = record()
        value["initial_capture_only"] = True
        result, runtime = self.recover(value)
        self.assertEqual(result["phase"], "recovery_required")
        self.assertNotIn("off", runtime.events)

    def test_changed_identity_restart_takeover_and_stale_pid_no_off(self):
        for changed in (
            "container_id",
            "restart_count",
            "started_at",
            "boot",
            "pid_start",
            "owner_alive",
        ):
            with self.subTest(changed=changed):
                value = record()
                runtime = Runtime()
                if changed == "boot":
                    value["owner"]["boot_id"] = "22222222-2222-4222-8222-222222222222"
                elif changed in ("pid_start", "owner_alive"):
                    value["owner"] = state.process_identity(os.getpid())
                    if changed == "pid_start":
                        value["owner"]["start_ticks"] += 1
                elif changed == "restart_count":
                    runtime.current[changed] = 1
                else:
                    runtime.current[changed] = "changed"
                result, runtime = self.recover(value, runtime)
                self.assertEqual(result["phase"], "recovery_required")
                self.assertNotIn("off", runtime.events)

    def test_off_failure_is_redacted_and_unresolved(self):
        runtime = Runtime()
        runtime.fail_off = True
        result, _ = self.recover(record(), runtime)
        self.assertEqual(result["phase"], "recovery_required")
        self.assertNotIn("sentinel", json.dumps(result))

    def test_recovery_requires_lease(self):
        with self.assertRaises(ValueError):
            state.recover_owned_run(self.directory, runtime=Runtime())

    def test_generation_takeover_preserves_new_owner_and_never_off(self):
        runtime = Runtime()
        other = record("paused")
        other["generation"] = "33333333-3333-4333-8333-333333333333"

        def cancel(children):
            state.write_state(self.directory, other)
            return True

        runtime.cancel_children = cancel
        result, runtime = self.recover(record(), runtime)
        self.assertEqual(result["phase"], "recovery_required")
        self.assertNotIn("off", runtime.events)
        self.assertEqual(state.read_state(self.directory)["generation"], other["generation"])

    def test_output_rejects_hardlink_and_wrong_owner(self):
        target = self.directory / "output"
        target.touch(mode=0o600)
        alias = self.directory / "alias"
        os.link(target, alias)
        with self.assertRaises((ValueError, OSError)):
            state.run_bounded(
                [sys.executable, "-c", "print('x')"],
                deadline=time.monotonic() + 1,
                stdout_path=alias,
            )
        self.assertEqual(target.read_text(), "")

    def test_authority_not_reusable_after_fork(self):
        with state.backup_lock(self.directory) as authority:
            pid = os.fork()
            if pid == 0:
                try:
                    state.validate_authority(authority, self.directory)
                except ValueError:
                    os._exit(0)
                os._exit(1)
            _, status = os.waitpid(pid, 0)
            self.assertEqual(os.waitstatus_to_exitcode(status), 0)

    def test_successful_command_reaps_background_descendants(self):
        marker = self.directory / "background"
        code = (
            "import os,time; p=os.fork();\nif p==0:\n"
            f" f=open({str(marker)!r},'a');\n"
            " while True: f.write('x'); f.flush(); time.sleep(.02)\n"
            "else: time.sleep(.08)"
        )
        with state.backup_lock(self.directory):
            self.assertEqual(
                state.run_bounded([sys.executable, "-c", code], deadline=time.monotonic() + 1), 0
            )
        before = marker.stat().st_size
        time.sleep(0.08)
        self.assertEqual(marker.stat().st_size, before)

    def test_stale_descendant_inventory_never_signals_foreign_process(self):
        foreign = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
        try:
            original = state._descendants
            with (
                state.backup_lock(self.directory),
                patch.object(
                    state, "_descendants", side_effect=lambda pid: [*original(pid), foreign.pid]
                ),
            ):
                with self.assertRaisesRegex(ValueError, "command_timeout"):
                    state.run_bounded(
                        [sys.executable, "-c", "import time; time.sleep(5)"],
                        deadline=time.monotonic() + 0.1,
                    )
            self.assertIsNone(foreign.poll(), "stale inventory killed unrelated process")
        finally:
            if foreign.poll() is None:
                foreign.kill()
            foreign.wait()

    def test_unavailable_pidfd_denied_before_starting_command(self):
        marker = self.directory / "should-not-start"
        with patch.object(state.os, "pidfd_open", side_effect=OSError("unsupported")):
            with self.assertRaisesRegex(ValueError, "process_supervision_unavailable"):
                state.run_bounded(
                    [sys.executable, "-c", f"open({str(marker)!r},'w').close()"],
                    deadline=time.monotonic() + 1,
                )
        self.assertFalse(marker.exists())

    def test_operator_wrapper_preserves_controlling_terminal_confirmation(self):
        import pty

        pid, master = pty.fork()
        if pid == 0:
            try:
                code = state._run_bounded(
                    [
                        sys.executable,
                        "-c",
                        "import os; f=os.open('/dev/tty',os.O_RDWR); assert os.read(f,1)==b'x'",
                    ],
                    deadline=time.monotonic() + 0.5,
                    inherit_output=True,
                )
                os._exit(code)
            except BaseException:
                os._exit(2)
        try:
            os.write(master, b"x\n")
            _, status = os.waitpid(pid, 0)
            self.assertEqual(os.waitstatus_to_exitcode(status), 0)
        finally:
            os.close(master)

    def test_bounded_timeout_reaps_real_grandchild(self):
        marker = self.directory / "mutations"
        code = (
            f"import os,time; os.fork(); f=open({str(marker)!r},'a');\n"
            "while True: f.write('x'); f.flush(); time.sleep(.02)"
        )
        with state.backup_lock(self.directory):
            with self.assertRaisesRegex(ValueError, "command_timeout"):
                state.run_bounded([sys.executable, "-c", code], deadline=time.monotonic() + 0.25)
        before = marker.stat().st_size
        time.sleep(0.12)
        self.assertEqual(marker.stat().st_size, before)
        state.assert_no_backup(self.directory)

    def test_parent_signal_reaps_real_child_and_escaped_grandchild(self):
        for sig in (signal.SIGTERM, signal.SIGKILL):
            with self.subTest(signal=sig):
                marker = self.directory / ("mutations-" + str(sig))
                ready = self.directory / ("ready-" + str(sig))
                child_code = (
                    "import os,time; p=os.fork();\nif p==0: os.setsid()\n"
                    f"f=open({str(marker)!r},'a');\n"
                    "while True: f.write('x'); f.flush(); time.sleep(.02)"
                )
                parent_code = (
                    "import sys,time,os,json; from pathlib import Path; "
                    f"sys.path.insert(0,{str(PATH.parent)!r}); import paired_backup_state as s;\n"
                    f"with s.backup_lock(Path({str(self.directory)!r})):\n"
                    f" value=json.loads({json.dumps(record())!r}); "
                    "value['owner']=s.process_identity(os.getpid()); "
                    f"s.write_state(Path({str(self.directory)!r}),value);\n"
                    f" Path({str(ready)!r}).touch(); "
                    f"s.run_bounded([sys.executable,'-c',{child_code!r}],"
                    "deadline=time.monotonic()+10)"
                )
                parent = subprocess.Popen(
                    [sys.executable, "-c", parent_code],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                try:
                    until = time.monotonic() + 3
                    while not marker.exists() and time.monotonic() < until:
                        time.sleep(0.01)
                    self.assertTrue(marker.exists())
                    with self.assertRaises(ValueError):
                        state.assert_no_backup(self.directory)
                    parent.send_signal(sig)
                    parent.wait(timeout=3)
                    until = time.monotonic() + 3
                    while time.monotonic() < until:
                        try:
                            with state.backup_lock(self.directory):
                                runtime = Runtime()
                                recovered = state.recover_owned_run(self.directory, runtime=runtime)
                                self.assertEqual(recovered["phase"], "resumed")
                                self.assertEqual(runtime.events, ["children_stopped", "off"])
                            break
                        except ValueError:
                            time.sleep(0.01)
                    else:
                        self.fail("supervisor failed to release lease after descendants exited")
                    before = marker.stat().st_size
                    time.sleep(0.12)
                    self.assertEqual(marker.stat().st_size, before)
                finally:
                    if parent.poll() is None:
                        parent.kill()
                        parent.wait()


if __name__ == "__main__":
    unittest.main()
