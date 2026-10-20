"""Real Docker handoff acceptance, invoked by the paired daemon fixture."""

import json
import os
import select
import signal
import subprocess
import time
import uuid
from pathlib import Path
from types import SimpleNamespace


def assert_native_transition(stopped_at, started_at, status):
    if started_at - stopped_at < 60:
        raise AssertionError("handoff_start_interval")
    if (
        status["capture_only"] is not False
        or status["mode_ack"] is not False
        or status["pending_count"] != 0
    ):
        raise AssertionError("native_off_ack_and_drain")


def run(c):
    """Use the production adapter; only manifest loading selects disposable scope."""
    h, state, control, paired = (c[k] for k in ("handoff", "state", "control", "paired"))
    command, manifest_path, new_path = c["command"], c["manifest_path"], c["new_path"]
    directory = Path(c["manifest"]["state_dir"])
    generation = str(uuid.uuid4())
    # Intentional initial recovery fixture, owned by an actual dead process.
    read_fd, write_fd = os.pipe()
    child = os.fork()
    if child == 0:
        os.close(read_fd)
        os.write(write_fd, json.dumps(state.process_identity(os.getpid())).encode())
        os._exit(0)
    os.close(write_fd)
    owner = json.loads(os.read(read_fd, 4096))
    os.close(read_fd)
    os.waitpid(child, 0)
    old_runtime = paired.Runtime.for_disposable(
        manifest_path, c["work"], c["stack"], sql_project=c["sql_project"]
    )
    value = dict(
        format_version=1,
        generation=generation,
        owner=owner,
        identity=old_runtime.identity(),
        phase="recovery_required",
        created_at=time.time(),
        updated_at=time.time(),
        initial_capture_only=False,
        children=[],
        failure_reason="off_unacknowledged",
    )
    with state.backup_lock(directory):
        state.write_state(directory, value)
    old_runtime.generation = generation
    orphan = old_runtime.job_name("control-off")
    c["register_job"](generation, value["identity"])
    labels = old_runtime.labels()
    command(
        [
            "docker",
            "create",
            "--name",
            orphan,
            "--network",
            "none",
            *sum((["--label", key + "=" + val] for key, val in labels.items()), []),
            c["helper"],
            "python",
            "-c",
            "pass",
        ]
    )
    args = SimpleNamespace(
        manifest=manifest_path,
        new_manifest=new_path,
        stack=c["stack"],
        generation=generation,
        state_sha256=h.digest(directory / state.STATE_NAME),
        manifest_sha256=h.digest(manifest_path),
        new_manifest_sha256=h.digest(new_path),
    )

    def make_adapter():
        result = h.LocalAdapter.for_disposable(
            args, state, control, paired, sql_project=c["sql_project"]
        )
        if c.get("migrate") is not None:
            result.migrate = lambda: c["migrate"](result)
        result.work.mkdir(mode=0o700, exist_ok=True)
        result.runtime.deadline = time.monotonic() + 900
        native_job = result.runtime.job

        def observed_job(kind, image, options, argv, output):
            c["register_job"](generation, result.runtime.identity())
            try:
                return native_job(kind, image, options, argv, output)
            except BaseException:
                # Only this synthetic fixture exports helper diagnostics.
                # Production CLI retains its redacted failure boundary.
                try:
                    logs = subprocess.run(
                        ["docker", "logs", result.runtime.job_name(kind)],
                        capture_output=True,
                        text=True,
                        timeout=15,
                    )
                    Path("/evidence/handoff-helper-error.log").write_text(logs.stdout + logs.stderr)
                except BaseException:
                    pass
                raise

        result.runtime.job = observed_job
        return result

    adapter = make_adapter()
    with state.backup_lock(directory), control.operator_lock(directory):
        h.Handoff(adapter).prepare()
        assert not command(["docker", "ps", "-aq", "--filter", "name=^/" + orphan + "$"]).strip()
        assert state.read_state(directory)["children"] == []
        # The initially empty spool permits a real return to the historical
        # image. No journal or runtime guards are bypassed.
        rolled_back = h.Handoff(adapter).rollback()
        assert rolled_back["phase"] == "recovery_required"
        assert adapter.target()["Image"] == c["manifest"]["image_id"]
        assert adapter.target()["State"]["Running"]
        assert adapter.journal_read()["phase"] == "rolled_back"
    args.state_sha256 = h.digest(directory / state.STATE_NAME)
    args.manifest_sha256 = h.digest(manifest_path)
    c["register_job"](generation, state.read_state(directory)["identity"])
    adapter = make_adapter()
    if c.get("seed") is not None:
        safety = adapter.safety

        def seed_then_capture():
            assert not adapter.target()["State"]["Running"]
            c["evidence"]["legacy_seed"] = c["seed"](adapter)
            return safety()

        adapter.safety = seed_then_capture
    with state.backup_lock(directory), control.operator_lock(directory):
        h.Handoff(adapter).prepare()
        stopped = time.monotonic()
    # Kill a real stage owner after durable prepare; leases must release while
    # journal continues to deny ordinary recovery, then same pins resume.
    read_fd, write_fd = os.pipe()
    child = os.fork()
    if child == 0:
        os.close(read_fd)
        native_wait = adapter.wait

        def announce_wait():
            # This is an observation point inside the real stage, after the
            # stopped candidate and start intent are both durable.
            os.write(write_fd, b"waiting")
            native_wait()

        adapter.wait = announce_wait
        with state.backup_lock(directory), control.operator_lock(directory):
            h.Handoff(adapter).switch()
        os._exit(2)
    os.close(write_fd)
    try:
        ready, _, _ = select.select([read_fd], [], [], 60)
        if not ready:
            raise AssertionError("switch_stage_did_not_enter_native_wait")
        assert os.read(read_fd, 32) == b"waiting"
        assert adapter.journal_read()["phase"] == "start_intent"
        assert adapter.target()["Image"] == c["new_manifest"]["image_id"]
        assert not adapter.target()["State"]["Running"]
    finally:
        os.close(read_fd)
        try:
            os.kill(child, signal.SIGKILL)
        except ProcessLookupError:
            pass
        _, code = os.waitpid(child, 0)
    assert os.WIFSIGNALED(code) and os.WTERMSIG(code) == signal.SIGKILL
    with state.backup_lock(directory):
        try:
            state.recover_owned_run(directory, runtime=old_runtime)
        except ValueError:
            pass
        else:
            raise AssertionError("ordinary_recovery_crossed_handoff")
    with state.backup_lock(directory), control.operator_lock(directory):
        h.Handoff(adapter).switch()
        started = time.monotonic()
        result = h.Handoff(adapter).finish()
        assert result["phase"] == "resumed"
    current = c["status"]()["status"]
    assert_native_transition(stopped, started, current)
    c["evidence"]["collector_handoff"] = dict(
        orphan_control_off_removed=True,
        initial_children_empty=True,
        empty_backlog_rollback=True,
        killed_stage_lease_released=True,
        ordinary_recovery_denied=True,
        start_interval_seconds=started - stopped,
        native_off_ack=True,
        pending_count=current["pending_count"],
        old_image_id=c["manifest"]["image_id"],
        new_image_id=c["new_manifest"]["image_id"],
    )
