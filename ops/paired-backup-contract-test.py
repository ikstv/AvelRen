"""Ізольовані контракти coordinator; runtime/remote boundaries синтетичні."""

import gzip
import hashlib
import importlib.util
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import paired_backup_state as state

PATH = Path(__file__).with_name("paired-backup.py")


def load():
    if not PATH.exists():
        raise AssertionError("paired backup coordinator is missing")
    spec = importlib.util.spec_from_file_location("paired_coordinator", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


IDENTITY = dict(
    container_id="a" * 64,
    image_id="sha256:" + "b" * 64,
    source_commit="c" * 40,
    restart_count=0,
    started_at="2026-01-01T00:00:00Z",
    volume="spool",
    network="network",
)


class Runtime:
    def __init__(self, events, fault=None):
        self.events, self.fault = events, fault
        self.mode, self.ack = fault == "existing", fault == "existing"
        self.changed = False
        self.deadline = time.monotonic() + 900

    def preflight(self):
        self.events.append("preflight")
        if self.fault == "preflight":
            raise ValueError("secret raw diagnostic")

    def verify_client(self):
        pass  # Synthetic Docker boundary; real client trust has dedicated cases.

    def identity(self):
        value = dict(IDENTITY)
        if self.changed:
            value["restart_count"] += 1
        return value

    def capture_status(self):
        resumed = "off" in self.events and not self.mode
        pending = 0
        error = None
        if resumed and self.fault == "drain_error":
            error = "secret writer detail"
        if resumed and self.fault == "never_drain":
            pending = 1
        if resumed and self.fault == "drain_progress":
            pending = getattr(self, "remaining_pending", 2)
            self.remaining_pending = max(0, pending - 1)
        return dict(
            capture_only=self.mode,
            mode_ack=self.ack,
            pending_count=pending,
            acked_count=1,
            last_error=error,
        )

    def capture_only(self, mode, authority):
        state.validate_authority(authority, authority.state_dir)
        self.events.append(mode)
        self.mode = mode == "on"
        self.ack = self.mode
        if self.fault == "on" and mode == "on":
            self.ack = None
            raise ValueError("command_timeout")
        if self.fault == "off" and mode == "off":
            self.ack = None
            raise ValueError("command_timeout")
        return self.capture_status()

    def cancel_children(self, children):
        self.events.append("cancel")
        return self.fault != "children"

    def sql_snapshot(self, directory, backup_id, generation):
        self.events.append("sql")
        if self.fault == "sql":
            raise ValueError("command_timeout")
        if self.fault == "signal":
            raise KeyboardInterrupt
        path = directory / f"avelren-{backup_id}.sql.gz"
        path.write_bytes(gzip.compress(os.urandom(12000)))
        path.chmod(0o600)
        return path

    def spool_snapshot(self, directory, backup_id, generation):
        self.events.append("spool")
        if self.fault == "spool":
            raise ValueError("command_timeout")
        data = b"synthetic detached helper output"
        path = directory / f"avelren-{backup_id}.spool.sqlite3.gz"
        path.write_bytes(gzip.compress(data))
        path.chmod(0o600)
        summary = dict(
            schema_version=1,
            payload_version=1,
            state_counts=dict(started=1, pending=1, acked=1),
            payload_count=2,
            cycle_range=dict(
                first_seq=1,
                last_seq=3,
                first_at="2026-01-01T00:00:00Z",
                last_at="2026-01-01T00:01:00Z",
            ),
            sha256=hashlib.sha256(data).hexdigest(),
            bytes=len(data),
        )
        self.changed = self.fault == "identity"
        if self.fault == "mode_changed":
            self.ack = False
        return path, summary


class Publisher:
    def __init__(self, runtime, fault=None):
        self.runtime, self.fault = runtime, fault
        self.before_manifest = lambda: None

    def preflight(self):
        if self.fault == "crypt":
            raise ValueError("wrong_crypt")

    def publish(self, manifest, directory):
        assert self.runtime.mode is False and self.runtime.ack is False
        self.runtime.events.extend(["upload4", "verify"])
        if self.fault == "writer_after_upload":
            self.runtime.fault = "drain_error"
        if self.fault == "slow_upload":
            time.sleep(max(0, self.deadline - time.monotonic()) + 0.03)
        self.before_manifest()
        self.runtime.events.extend(["manifest", "readback", "retention"])
        if self.fault == "writer_after_publish":
            self.runtime.fault = "drain_error"
        if self.fault == "network":
            raise ValueError("secret quota diagnostic")
        return [
            "crypt:paired/" + manifest["tier"] + "/" + p.name
            for p in directory.iterdir()
            if p.name.startswith("avelren-")
        ]


class CoordinatorContracts(unittest.TestCase):
    def setUp(self):
        self.module = load()
        self.temp = tempfile.TemporaryDirectory(dir="/root")
        self.root = Path(self.temp.name)
        self.root.chmod(0o700)
        self.state = self.root / "state"
        self.state.mkdir(mode=0o700)
        self.work = self.root / "work"
        self.work.mkdir(mode=0o700)
        self.stamp = self.root / "stamp"
        self.stamp.write_text("old stamp")
        self.stamp.chmod(0o600)
        self.receipt = self.root / "receipt"

    def tearDown(self):
        self.temp.cleanup()

    def execute(self, fault=None, remote_fault=None):
        self.events = []
        self.runtime = Runtime(self.events, fault)
        publisher = Publisher(self.runtime, remote_fault)
        coordinator = self.module.Coordinator(
            self.state, self.work, self.runtime, publisher, self.receipt, self.stamp
        )
        return coordinator.run()

    def test_order_and_success_evidence(self):
        result = self.execute()
        self.assertEqual(
            self.events,
            [
                "preflight",
                "on",
                "sql",
                "spool",
                "cancel",
                "off",
                "upload4",
                "verify",
                "manifest",
                "readback",
                "retention",
            ],
        )
        self.assertEqual(result["status"], "paired_backup_verified")
        receipt = json.loads(self.receipt.read_text())
        self.assertEqual(receipt["backup_id"], result["backup_id"])
        self.assertEqual(len(receipt["manifest_sha256"]), 64)
        self.assertTrue(receipt["writer_resumed"])
        self.assertEqual(state.read_state(self.state)["phase"], "published")
        self.assertEqual(list(self.work.iterdir()), [])

    def test_preflight_is_already_durably_owned(self):
        original = Runtime.preflight

        def preflight(runtime):
            value = state.read_state(self.state)
            self.assertIsNotNone(value, "first creating preflight lacks durable ownership")
            self.assertEqual(value["generation"], runtime.generation)
            self.assertEqual(value["identity"], runtime.identity())
            self.assertEqual(value["phase"], "prepared")
            self.assertFalse(value["initial_capture_only"])
            return original(runtime)

        with patch.object(Runtime, "preflight", preflight):
            self.execute()

    def test_control_helper_is_not_classified_as_an_extra_producer(self):
        runtime = self.module.Runtime(dict(state_dir=str(self.state), volume="spool"), self.work)
        runtime.generation = "12345678-1234-1234-1234-123456789abc"
        runtime.owned_job_record = lambda: dict(phase="on_intent", initial_capture_only=False)
        runtime.helper, runtime.helper_hash = IDENTITY["image_id"], "a" * 64
        runtime.verify_helper_image = lambda: None
        runtime.cancel_jobs = lambda kinds: True
        commands = []

        def job(kind, image, options, command, output):
            commands.append(command)
            output.write_text('{"capture_only":true,"mode_ack":true}')

        runtime.job = job
        runtime.control_job("on")
        container = dict(Name="/" + runtime.job_name("control-on"),
                         Config=dict(Cmd=commands[0][1:], Entrypoint=commands[0][:1]))
        self.assertFalse(runtime.controller.runtime.is_collector(container))

    def test_failures_owned_cleanup_and_no_success(self):
        for fault in [
            "on",
            "sql",
            "spool",
            "identity",
            "off",
            "children",
            "signal",
            "mode_changed",
            "preflight",
            "existing",
        ]:
            with self.subTest(fault=fault):
                with self.assertRaises((ValueError, KeyboardInterrupt)):
                    self.execute(fault)
                self.assertEqual(self.stamp.read_text(), "old stamp")
                self.assertFalse(self.receipt.exists())
                self.assertNotIn("upload4", self.events)
                should_off = fault in {"on", "sql", "spool", "off", "signal", "mode_changed"}
                self.assertEqual("off" in self.events, should_off)
                if fault == "identity":
                    self.assertEqual(
                        state.read_state(self.state)["failure_reason"], "identity_changed"
                    )
                (self.state / state.STATE_NAME).unlink(missing_ok=True)

    def test_network_failure_resolved_state_and_old_stamp(self):
        with self.assertRaises(ValueError):
            self.execute(remote_fault="network")
        value = state.read_state(self.state)
        self.assertEqual((value["phase"], value["failure_reason"]), ("resumed", "network_failed"))
        self.assertEqual(self.stamp.read_text(), "old stamp")
        self.assertFalse(self.receipt.exists())
        with state.operator_guard(self.state):
            pass

    def test_wrong_crypt_before_pause(self):
        with self.assertRaises(ValueError):
            self.execute(remote_fault="crypt")
        self.assertNotIn("on", self.events)
        self.assertIsNone(state.read_state(self.state))

    def test_takeover_during_off_ack_is_preserved(self):
        original = Runtime.capture_only
        replacement = []

        def takeover(runtime, mode, authority):
            result = original(runtime, mode, authority)
            if mode == "off":
                value = state.read_state(self.state)
                value["generation"] = "87654321-4321-4321-4321-cba987654321"
                state.write_state(self.state, value)
                replacement.append((self.state / state.STATE_NAME).read_bytes())
            return result

        with patch.object(Runtime, "capture_only", takeover):
            with self.assertRaisesRegex(ValueError, "ownership_unproven"):
                self.execute()
        self.assertEqual((self.state / state.STATE_NAME).read_bytes(), replacement[0])
        self.assertNotIn("upload4", self.events)
        self.assertEqual(self.events.count("off"), 1)
        self.assertFalse(self.receipt.exists())
        self.assertEqual(self.stamp.read_text(), "old stamp")

    def test_takeover_before_cleanup_is_never_overwritten(self):
        replacement = []

        def takeover(runtime, *args):
            value = state.read_state(self.state)
            value["generation"] = "87654321-4321-4321-4321-cba987654321"
            state.write_state(self.state, value)
            replacement.append((self.state / state.STATE_NAME).read_bytes())
            raise ValueError("copy_failed")

        with patch.object(Runtime, "sql_snapshot", takeover), self.assertRaises(ValueError):
            self.execute()
        self.assertEqual((self.state / state.STATE_NAME).read_bytes(), replacement[0])
        self.assertNotIn("off", self.events)
        self.assertNotIn("upload4", self.events)
        self.assertFalse(self.receipt.exists())
        self.assertEqual(self.stamp.read_text(), "old stamp")

    def test_takeover_after_resume_network_failure_is_preserved(self):
        replacement = []

        def takeover(publisher, *args):
            value = state.read_state(self.state)
            value["generation"] = "87654321-4321-4321-4321-cba987654321"
            state.write_state(self.state, value)
            replacement.append((self.state / state.STATE_NAME).read_bytes())
            raise ValueError("network_failed")

        with patch.object(Publisher, "publish", takeover), self.assertRaises(ValueError):
            self.execute()
        self.assertEqual((self.state / state.STATE_NAME).read_bytes(), replacement[0])
        self.assertEqual(self.events.count("off"), 1)
        self.assertFalse(self.receipt.exists())
        self.assertEqual(self.stamp.read_text(), "old stamp")

    def slow_python(self, operation):
        wrapper = self.root / "slow-python"
        marker = self.root / "worker-entered"
        wrapper.write_text(
            "#!/bin/bash\n"
            f'if [ "$3" = "{operation}" ]; then touch "{marker}"; sleep 2; fi\n'
            f'exec "{sys.executable}" "$@"\n'
        )
        wrapper.chmod(0o700)
        return wrapper

    def test_slow_local_digest_obeys_remaining_network_budget(self):
        wrapper = self.slow_python("digest")
        with (
            patch.object(self.module, "NETWORK_SECONDS", 0.25),
            patch.object(sys, "executable", str(wrapper)),
        ):
            started = time.monotonic()
            with self.assertRaisesRegex(ValueError, "command_timeout"):
                self.execute()
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(state.read_state(self.state)["phase"], "resumed")
        self.assertFalse(self.receipt.exists())
        self.assertEqual(self.stamp.read_text(), "old stamp")
        self.assertNotIn("upload4", self.events)

    def test_slow_local_gzip_validation_obeys_same_budget(self):
        wrapper = self.slow_python("verify")
        with (
            patch.object(self.module, "NETWORK_SECONDS", 1.5),
            patch.object(sys, "executable", str(wrapper)),
        ):
            started = time.monotonic()
            with self.assertRaisesRegex(ValueError, "command_timeout"):
                self.execute()
        self.assertLess(time.monotonic() - started, 2.2)
        self.assertTrue((self.root / "worker-entered").exists())
        self.assertEqual(state.read_state(self.state)["phase"], "resumed")
        self.assertFalse(self.receipt.exists())
        self.assertEqual(self.stamp.read_text(), "old stamp")
        self.assertNotIn("upload4", self.events)

    def test_runtime_commands_drop_ambient_interpolation_and_docker_context(self):
        runtime = self.module.Runtime(dict(state_dir=str(self.state)), self.work)
        observed = []

        def runner(argv, *, deadline, env=None, stdout_path=None):
            observed.append(env)
            stdout_path.write_text("verified")
            return 0

        with (
            patch.dict(
                os.environ,
                DB_IMAGE="unapproved-image",
                DOCKER_HOST="tcp://unapproved:2375",
                DOCKER_CONTEXT="unapproved",
                DOCKER_CONFIG="/unapproved",
                AVELREN_BACKUP_PASSWORD="secret-test-value",
                PGPASSWORD="ambient-secret",
            ),
            patch.object(state, "run_bounded", runner),
        ):
            runtime.output(["docker", "compose", "config"], env=dict(os.environ))
            runtime.output(["docker", "inspect", "synthetic"])
        for env in observed:
            self.assertIsNotNone(env)
            self.assertNotIn("DB_IMAGE", env)
            self.assertNotIn("DOCKER_CONTEXT", env)
            self.assertNotIn("AVELREN_BACKUP_PASSWORD", env)
            self.assertNotIn("PGPASSWORD", env)
            self.assertEqual(env["DOCKER_HOST"], "unix:///var/run/docker.sock")
            self.assertEqual(env["DOCKER_CONFIG"], "/etc/avelren/docker-client")

    def test_only_sql_create_receives_backup_password(self):
        runtime = self.module.Runtime(dict(state_dir=str(self.state)), self.work)
        runtime.generation = "12345678-1234-1234-1234-123456789abc"
        runtime.identity = lambda: dict(IDENTITY)
        runtime.owned_job_record = lambda: {}  # This test isolates credential delivery only.
        calls = []

        def output(argv, env=None):
            calls.append((argv, env))
            if argv[1] == "create":
                return "f" * 64
            return json.dumps([dict(State=dict(Running=False, ExitCode=0))])

        runtime.output = output
        with (
            patch.dict(
                os.environ, AVELREN_BACKUP_PASSWORD="secret-test-value", DB_IMAGE="unapproved"
            ),
            patch.object(state, "run_bounded", return_value=0),
        ):
            runtime.job(
                "check",
                IDENTITY["image_id"],
                ["--network", "none"],
                ["python", "-c", "print('synthetic')"],
                self.work / "check",
            )
            runtime.job(
                "sql",
                IDENTITY["image_id"],
                ["--network", "network", "-e", "PGPASSWORD"],
                ["pg_dump", "--no-owner", "-U", "avelren_backup"],
                self.work / "sql",
            )
        create = [(argv, env) for argv, env in calls if argv[1] == "create"]
        self.assertNotIn("PGPASSWORD", create[0][1] or {})
        self.assertNotIn("AVELREN_BACKUP_PASSWORD", create[0][1] or {})
        self.assertNotIn("DB_IMAGE", create[1][1])
        self.assertEqual(create[1][1]["PGPASSWORD"], "secret-test-value")

    def test_docker_client_config_requires_empty_context_and_approved_plugin(self):
        client = self.root / "docker-client"
        client.mkdir(mode=0o700)
        plugins = client / "cli-plugins"
        plugins.mkdir(mode=0o700)
        plugin = plugins / "docker-compose"
        plugin.write_bytes(b"synthetic approved executable")
        plugin.chmod(0o700)
        config = client / "config.json"
        config.write_text("{}")
        config.chmod(0o600)
        runtime = self.module.Runtime(dict(state_dir=str(self.state)), self.work)
        runtime.output = lambda *args, **kwargs: json.dumps(dict(version="v5.5.1"))
        sha = hashlib.sha256(plugin.read_bytes()).hexdigest()
        with (
            patch.object(self.module, "DOCKER_CLIENT_DIR", client, create=True),
            patch.dict(os.environ, AVELREN_BACKUP_COMPOSE_SHA256=sha),
        ):
            runtime.verify_client()
            config.write_text('{"currentContext":"unapproved"}')
            with self.assertRaisesRegex(ValueError, "docker_client_config_invalid"):
                runtime.verify_client()
            config.write_text("{}")
            with patch.dict(os.environ, AVELREN_BACKUP_COMPOSE_SHA256="f" * 64):
                with self.assertRaisesRegex(ValueError, "compose_plugin_hash_mismatch"):
                    runtime.verify_client()
            runtime.output = lambda *args, **kwargs: json.dumps(dict(version="v0.0.0"))
            with self.assertRaisesRegex(ValueError, "compose_plugin_version_mismatch"):
                runtime.verify_client()

    def test_private_sql_helper_output_is_never_reopened_unsafely(self):
        runtime = self.module.Runtime(dict(state_dir=str(self.state)), self.work)
        raw = self.work / "raw"
        raw.write_bytes(os.urandom(30000))
        raw.chmod(0o600)
        destination = self.work / "sql.gz"
        runtime.deadline = time.monotonic() + 1
        runtime.compress(raw, destination)
        self.assertGreater(len(gzip.decompress(destination.read_bytes())), 20000)
        self.assertEqual(destination.stat().st_mode & 0o777, 0o600)
        self.assertFalse(raw.exists())

    def test_native_preflight_status_has_no_invented_ready_field(self):
        runtime = self.module.Runtime(dict(state_dir=str(self.state)), self.work)
        runtime.verify_client = lambda: None
        helper = "sha256:" + "d" * 64
        imported_hash = "e" * 64
        runtime.identity = lambda: dict(IDENTITY)
        runtime.cancel_children = lambda children: True
        runtime.prepare_sql = lambda: None
        runtime.output = lambda *args, **kwargs: json.dumps(
            [dict(Id=helper, Config=dict(Env=["AVELREN_GIT_SHA=" + "c" * 40]))]
        )
        runtime.job = lambda kind, image, options, command, output: output.write_text(imported_hash)
        runtime.controller.execute = lambda *args, **kwargs: dict(
            pending_count=1,
            acked_count=1,
            capture_only=False,
            mode_ack=False,
            max_cycle_bytes=1000,
            spool_bytes=2000,
            last_error=None,
            oldest_pending_at=None,
        )
        with patch.dict(
            os.environ,
            AVELREN_BACKUP_PASSWORD="secret-test-value",
            AVELREN_BACKUP_HELPER_IMAGE=helper,
            AVELREN_BACKUP_HELPER_SOURCE_COMMIT="c" * 40,
            AVELREN_BACKUP_HELPER_SHA256=imported_hash,
        ):
            runtime.preflight()

    def test_term_signal_uses_owned_cleanup_before_propagating(self):
        original = Runtime.sql_snapshot

        def terminated(runtime, *args):
            os.kill(os.getpid(), signal.SIGTERM)
            return original(runtime, *args)

        saved = signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
        try:
            with (
                patch.object(Runtime, "sql_snapshot", terminated),
                self.assertRaises(KeyboardInterrupt),
            ):
                self.execute()
        finally:
            signal.signal(signal.SIGTERM, saved)
        self.assertIn("cancel", self.events)
        self.assertIn("off", self.events)
        self.assertFalse(self.runtime.mode)
        self.assertEqual(self.stamp.read_text(), "old stamp")

    def test_failed_stamp_write_removes_new_receipt(self):
        original = self.module.atomic_evidence

        def fail_stamp(path, data):
            if path == self.stamp:
                raise OSError("secret raw write error")
            original(path, data)

        with patch.object(self.module, "atomic_evidence", fail_stamp), self.assertRaises(OSError):
            self.execute()
        self.assertFalse(self.receipt.exists())
        self.assertEqual(self.stamp.read_text(), "old stamp")

    def test_job_cleanup_requires_matching_labels_and_stopped_inspection(self):
        runtime = self.module.Runtime(dict(state_dir=str(self.state)), self.work)
        runtime.generation = "12345678-1234-1234-1234-123456789abc"
        runtime.identity = lambda: dict(IDENTITY)
        name = runtime.job_name("spool")
        job = dict(
            Id="f" * 64,
            Name="/" + name,
            Config=dict(Labels=runtime.labels()),
            State=dict(Running=True),
        )
        calls = []
        present = [True]
        refuse_stop = [False]

        def output(argv, **kwargs):
            calls.append(argv)
            if argv[1] == "ps":
                return job["Id"] if present[0] and name in argv[-1] else ""
            if argv[1] == "inspect":
                return json.dumps([job])
            if argv[1] == "stop":
                if not refuse_stop[0]:
                    job["State"]["Running"] = False
                return job["Id"]
            if argv[1] == "rm":
                present[0] = False
                return job["Id"]
            raise AssertionError(argv)

        runtime.output = output
        self.assertTrue(runtime.cancel_children([]))
        self.assertEqual([a[1] for a in calls if a[1] in {"stop", "rm"}], ["stop", "rm"])
        present[0] = True
        job["State"]["Running"] = True
        job["Config"]["Labels"]["org.avelren.backup.generation"] = "foreign"
        calls.clear()
        self.assertFalse(runtime.cancel_children([]))
        self.assertNotIn("stop", [a[1] for a in calls])
        job["Config"]["Labels"] = runtime.labels()
        refuse_stop[0] = True
        calls.clear()
        self.assertFalse(runtime.cancel_children([]))
        self.assertNotIn("rm", [a[1] for a in calls])

    def test_helper_create_has_generation_identity_and_no_secret_arguments(self):
        runtime = self.module.Runtime(dict(state_dir=str(self.state)), self.work)
        runtime.generation = "12345678-1234-1234-1234-123456789abc"
        runtime.identity = lambda: dict(IDENTITY)
        runtime.owned_job_record = lambda: {}  # Creation ownership has separate daemon probes.
        calls = []

        def output(argv, env=None):
            calls.append((argv, env))
            if argv[1] == "create":
                return "f" * 64
            return json.dumps([dict(State=dict(Running=False, ExitCode=0))])

        runtime.output = output
        with (
            patch.dict(os.environ, AVELREN_BACKUP_PASSWORD="secret-test-value"),
            patch.object(state, "run_bounded", return_value=0),
        ):
            runtime.job(
                "sql",
                IDENTITY["image_id"],
                ["--network", "network", "-e", "PGPASSWORD"],
                ["pg_dump", "--no-owner", "-U", "avelren_backup", "-d", "avelren"],
                self.work / "dump",
            )
        argv, env = calls[0]
        self.assertIn(runtime.job_name("sql"), argv)
        self.assertIn(IDENTITY["image_id"], argv)
        self.assertNotIn("secret-test-value", " ".join(argv))
        self.assertEqual(env["PGPASSWORD"], "secret-test-value")

    def test_preflight_requires_verified_check_job_cancellation(self):
        runtime = self.module.Runtime(dict(state_dir=str(self.state)), self.work)
        runtime.verify_client = lambda: None
        helper = "sha256:" + "d" * 64
        runtime.identity = lambda: dict(IDENTITY)
        runtime.cancel_children = lambda children: False
        runtime.prepare_sql = lambda: None
        runtime.output = lambda *args, **kwargs: json.dumps(
            [dict(Id=helper, Config=dict(Env=["AVELREN_GIT_SHA=" + "c" * 40]))]
        )
        runtime.job = lambda kind, image, options, command, output: output.write_text("e" * 64)
        runtime.controller.execute = lambda *args, **kwargs: dict(max_cycle_bytes=1000)
        with patch.dict(
            os.environ,
            AVELREN_BACKUP_PASSWORD="secret-test-value",
            AVELREN_BACKUP_HELPER_IMAGE=helper,
            AVELREN_BACKUP_HELPER_SOURCE_COMMIT="c" * 40,
            AVELREN_BACKUP_HELPER_SHA256="e" * 64,
        ):
            with self.assertRaisesRegex(ValueError, "children_unresolved"):
                runtime.preflight()

    def test_recovery_cli_no_state_and_completed_state_are_idempotent(self):
        env = self.root / "runtime.env"
        compose = self.root / "compose.yml"
        env.write_text("SYNTHETIC=yes\n")
        compose.write_text("services: {}\n")
        env.chmod(0o600)
        compose.chmod(0o600)
        manifest = self.root / "manifest.json"
        manifest.write_text(
            json.dumps(
                dict(
                    source_commit=IDENTITY["source_commit"],
                    image_id=IDENTITY["image_id"],
                    env_file=str(env),
                    compose_file=str(compose),
                    state_dir=str(self.state),
                    project="avelren-collector-runtime",
                    container_name="avelren-collector-1",
                    network="avelren_default",
                    volume="avelren_collector_spool_v1",
                )
            )
        )
        manifest.chmod(0o600)
        argv = [
            "paired-backup.py",
            "recover",
            "--manifest",
            str(manifest),
            "--state-dir",
            str(self.state),
        ]
        with patch.object(sys, "argv", argv):
            self.assertEqual(self.module.main(), 0)
        self.execute()
        before = (self.state / state.STATE_NAME).read_bytes()
        with (
            patch.object(sys, "argv", argv),
            patch.dict(os.environ, AVELREN_BACKUP_MODE="sql-only"),
        ):
            self.assertEqual(self.module.main(), 0)
            self.assertEqual(self.module.main(), 0)
        self.assertEqual((self.state / state.STATE_NAME).read_bytes(), before)

    def test_shared_lock_rejects_second_run_before_pause(self):
        with state.backup_lock(self.state):
            with self.assertRaisesRegex(ValueError, "backup_busy"):
                self.execute()
        self.assertEqual(self.events, [])

    def test_dead_owner_recovery_adapter_still_runs_when_mode_is_sql_only(self):
        read_fd, write_fd = os.pipe()
        pid = os.fork()
        if pid == 0:
            os.close(read_fd)
            os.write(write_fd, json.dumps(state.process_identity(os.getpid())).encode())
            os.close(write_fd)
            os._exit(0)
        os.close(write_fd)
        owner = json.loads(os.read(read_fd, 4096))
        os.close(read_fd)
        os.waitpid(pid, 0)
        runtime = Runtime([])
        runtime.mode, runtime.ack = True, None
        now = time.time()
        value = dict(
            format_version=1,
            generation="12345678-1234-1234-1234-123456789abc",
            owner=owner,
            identity=IDENTITY,
            phase="on_intent",
            created_at=now,
            updated_at=now,
            initial_capture_only=False,
            children=[],
        )
        with state.backup_lock(self.state):
            state.write_state(self.state, value)
            with patch.dict(os.environ, AVELREN_BACKUP_MODE="sql-only"):
                recovered = state.recover_owned_run(self.state, runtime=runtime)
        self.assertEqual(recovered["phase"], "resumed")
        self.assertEqual(runtime.events, ["cancel", "off"])
        self.assertFalse(runtime.mode)

    def test_work_capacity_denied_before_helper_runs(self):
        runtime = self.module.Runtime(dict(state_dir=str(self.state)), self.work)
        runtime.identity = lambda: dict(IDENTITY)
        with patch.object(
            self.module.shutil, "disk_usage", return_value=type("Usage", (), {"free": 1})()
        ):
            with self.assertRaisesRegex(ValueError, "work_space_insufficient"):
                runtime.preflight()

    def test_helper_image_baked_database_secret_is_denied(self):
        runtime = self.module.Runtime(dict(state_dir=str(self.state)), self.work)
        runtime.verify_client = lambda: None
        helper = "sha256:" + "d" * 64
        runtime.identity = lambda: dict(IDENTITY)
        runtime.job = lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("helper_started"))
        runtime.output = lambda *args, **kwargs: json.dumps(
            [
                dict(
                    Id=helper,
                    Config=dict(
                        Env=["AVELREN_GIT_SHA=" + "c" * 40, "DATABASE_URL=secret-test-value"]
                    ),
                )
            ]
        )
        with patch.dict(
            os.environ,
            AVELREN_BACKUP_PASSWORD="secret-test-value",
            AVELREN_BACKUP_HELPER_IMAGE=helper,
            AVELREN_BACKUP_HELPER_SOURCE_COMMIT="c" * 40,
            AVELREN_BACKUP_HELPER_SHA256="e" * 64,
        ):
            with self.assertRaisesRegex(ValueError, "helper_credentials_forbidden"):
                runtime.preflight()

    def test_sql_context_rejects_container_created_from_other_compose_files(self):
        stack = self.root / "stack"
        stack.mkdir(mode=0o700)
        files = [stack / "docker-compose.yml", stack / "docker-compose.override.yml"]
        for path in [*files, stack / ".env"]:
            path.write_text("synthetic")
            path.chmod(0o600)
        runtime = self.module.Runtime(
            dict(state_dir=str(self.state), network="network"), self.work, stack
        )
        image = "sha256:" + "d" * 64
        db = dict(
            Id="f" * 64,
            Image=image,
            State=dict(Running=True),
            Config=dict(
                Labels={
                    "com.docker.compose.project": "avelren",
                    "com.docker.compose.service": "db",
                    "com.docker.compose.project.config_files": "/other/compose.yml",
                    "com.docker.compose.project.working_dir": str(stack),
                }
            ),
            NetworkSettings=dict(Networks=dict(network=dict(IPAddress="172.20.0.3"))),
        )

        def output(argv, **kwargs):
            if "config" in argv:
                return json.dumps(dict(services=dict(db=dict(image=image))))
            if "ps" in argv:
                return db["Id"]
            if "image" in argv:
                return json.dumps([dict(Id=image)])
            return json.dumps([db])

        runtime.output = output
        with patch.dict(os.environ, AVELREN_BACKUP_COMPOSE_FILES=":".join(map(str, files))):
            with self.assertRaisesRegex(ValueError, "sql_database_identity_mismatch"):
                runtime.prepare_sql()
            labels = db["Config"]["Labels"]
            labels["com.docker.compose.project.config_files"] = ",".join(map(str, files))
            runtime.prepare_sql()
            self.assertEqual(runtime._sql_project, "avelren")
            runtime._sql_project = "avelren-runtime-test-labels-sql"
            with self.assertRaisesRegex(ValueError, "sql_database_identity_mismatch"):
                runtime.prepare_sql()
            labels["com.docker.compose.project"] = runtime._sql_project
            runtime.prepare_sql()
            labels["com.docker.compose.project"] = "avelren-runtime-test-foreign-sql"
            with self.assertRaisesRegex(ValueError, "sql_database_identity_mismatch"):
                runtime.prepare_sql()
            labels["com.docker.compose.project"] = runtime._sql_project
            for key, wrong in (
                ("com.docker.compose.service", "migrator"),
                ("com.docker.compose.project.config_files", ",".join(map(str, reversed(files)))),
                ("com.docker.compose.project.working_dir", "/other"),
            ):
                with self.subTest(label=key), patch.dict(labels, {key: wrong}):
                    with self.assertRaisesRegex(ValueError, "sql_database_identity_mismatch"):
                        runtime.prepare_sql()
            for target, changes in (
                (db["State"], dict(Running=False)),
                (db, dict(Image="sha256:" + "e" * 64)),
                (db["NetworkSettings"], dict(Networks={})),
            ):
                with patch.dict(target, changes):
                    with self.assertRaisesRegex(ValueError, "sql_database_identity_mismatch"):
                        runtime.prepare_sql()

    def test_sql_context_ignores_unrelated_required_compose_environment(self):
        if not shutil.which("docker"):
            self.skipTest("native Docker Compose required")
        stack = self.root / "sql-stack"
        stack.mkdir(mode=0o700)
        compose = stack / "docker-compose.yml"
        image = "timescale/timescaledb:2.30.1-pg16@sha256:" + "a" * 64
        compose.write_text(
            f"services:\n  db:\n    image: {image}\n"
            "  migrator:\n    image: unused-fixture\n    environment:\n"
            "      DATABASE_URL: ${AVELREN_RELEASE_MIGRATOR_DSN:?required}\n"
        )
        compose.chmod(0o600)
        (stack / ".env").write_text("")
        (stack / ".env").chmod(0o600)
        runtime = self.module.Runtime(dict(network="network"), self.work, stack)
        db = dict(
            Id="f" * 64,
            Image="sha256:" + "d" * 64,
            State=dict(Running=True),
            Config=dict(
                Labels={
                    "com.docker.compose.project": "avelren",
                    "com.docker.compose.service": "db",
                    "com.docker.compose.project.config_files": str(compose),
                    "com.docker.compose.project.working_dir": str(stack),
                }
            ),
            NetworkSettings=dict(Networks=dict(network=dict(IPAddress="172.20.0.3"))),
        )
        ids = db["Id"]

        def output(argv, **kwargs):
            if argv[:2] == ["docker", "compose"]:
                return subprocess.check_output(argv, text=True, timeout=30, **kwargs)
            if argv[:2] == ["docker", "ps"]:
                self.assertEqual(
                    argv[2:],
                    [
                        "--quiet",
                        "--no-trunc",
                        "--filter",
                        "label=com.docker.compose.project=avelren",
                        "--filter",
                        "label=com.docker.compose.service=db",
                    ],
                )
                self.assertNotIn("AVELREN_RELEASE_MIGRATOR_DSN", kwargs["env"])
                return ids
            if argv == ["docker", "image", "inspect", image]:
                return json.dumps([dict(Id="sha256:" + "d" * 64)])
            if argv == ["docker", "inspect", "f" * 64]:
                return json.dumps([db])
            self.fail(f"unexpected command: {argv}")

        runtime.output = output
        with patch.dict(os.environ, AVELREN_BACKUP_COMPOSE_FILES=str(compose)):
            runtime.prepare_sql()
            self.assertEqual(runtime.db_id, "f" * 64)
            self.assertEqual(runtime.db_address, "172.20.0.3")
            for candidates in ("", "f" * 64 + "\n" + "e" * 64):
                ids = candidates
                with self.assertRaisesRegex(ValueError, "sql_database_identity_required"):
                    runtime.prepare_sql()
            ids = "f" * 64
            for unresolved in ("${DB_IMAGE}", "$DB_IMAGE", "$$DB_IMAGE"):
                with self.subTest(unresolved=unresolved):
                    compose.write_text(json.dumps(dict(services=dict(db=dict(image=unresolved)))))
                    with self.assertRaisesRegex(ValueError, "sql_database_image_required"):
                        runtime.prepare_sql()
            for invalid in ({}, dict(image=""), dict(image=None), dict(image=12)):
                with self.subTest(image=invalid):
                    # Keep invalid image shapes at the parser boundary: native Compose
                    # rejects some shapes before returning JSON.
                    native_output = runtime.output
                    runtime.output = lambda argv, value=invalid, native=native_output, **kw: (
                        json.dumps(dict(services=dict(db=value)))
                        if "config" in argv
                        else native(argv, **kw)
                    )
                    with self.assertRaisesRegex(ValueError, "sql_database_image_required"):
                        runtime.prepare_sql()
                    runtime.output = native_output

    def test_progress_drains_before_manifest_and_success(self):
        with patch.object(self.module, "DRAIN_POLL_SECONDS", 0.01, create=True):
            result = self.execute("drain_progress")
        statuses = result["writer_status"]
        self.assertEqual(statuses[0]["pending_count"], 0)
        self.assertEqual(
            [s["stage"] for s in statuses], ["resumed", "before_manifest", "published"]
        )
        self.assertEqual(self.runtime.remaining_pending, 0)
        self.assertTrue(all(not s["last_error_present"] for s in statuses))

    def test_writer_error_fails_resumed_without_manifest_receipt_stamp(self):
        with self.assertRaisesRegex(ValueError, "writer_error"):
            self.execute("drain_error")
        value = state.read_state(self.state)
        self.assertEqual(value["phase"], "resumed")
        self.assertEqual(value["failure_reason"], "network_failed")
        self.assertEqual(self.events.count("off"), 1)
        self.assertNotIn("manifest", self.events)
        self.assertFalse(self.receipt.exists())
        self.assertEqual(self.stamp.read_text(), "old stamp")
        self.assertNotIn("secret writer detail", (self.state / state.STATE_NAME).read_text())

    def test_never_draining_uses_shared_deadline_and_does_not_pause_again(self):
        with (
            patch.object(self.module, "NETWORK_SECONDS", 0.08, create=True),
            patch.object(self.module, "DRAIN_POLL_SECONDS", 0.01, create=True),
        ):
            started = time.monotonic()
            with self.assertRaisesRegex(ValueError, "drain_timeout"):
                self.execute("never_drain")
        self.assertLess(time.monotonic() - started, 1)
        self.assertEqual(state.read_state(self.state)["phase"], "resumed")
        self.assertEqual(self.events.count("off"), 1)
        self.assertEqual(self.events.count("on"), 1)
        self.assertFalse(self.receipt.exists())
        self.assertEqual(self.stamp.read_text(), "old stamp")

    def test_boundary_writer_errors_never_issue_success(self):
        for fault in ["writer_after_upload", "writer_after_publish"]:
            with self.subTest(fault=fault), self.assertRaisesRegex(ValueError, "writer_error"):
                self.execute(remote_fault=fault)
            self.assertEqual(state.read_state(self.state)["phase"], "resumed")
            self.assertFalse(self.receipt.exists())
            self.assertEqual(self.stamp.read_text(), "old stamp")
            self.assertEqual(self.events.count("off"), 1)
            if fault == "writer_after_upload":
                self.assertNotIn("manifest", self.events)

    def test_upload_and_drain_share_one_budget(self):
        with patch.object(self.module, "NETWORK_SECONDS", 3):
            with self.assertRaisesRegex(ValueError, "drain_timeout"):
                self.execute(remote_fault="slow_upload")
        self.assertEqual(state.read_state(self.state)["phase"], "resumed")
        self.assertNotIn("manifest", self.events)
        self.assertFalse(self.receipt.exists())
        self.assertEqual(self.stamp.read_text(), "old stamp")


class PublicationContracts(unittest.TestCase):
    def setUp(self):
        self.module = load()
        self.temp = tempfile.TemporaryDirectory(dir="/root")
        self.root = Path(self.temp.name)
        self.root.chmod(0o700)
        self.directory = self.root / "pair"
        self.directory.mkdir(mode=0o700)
        self.bin = self.root / "bin"
        self.bin.mkdir(mode=0o700)
        script = self.bin / "rclone"
        script.write_text("""#!/usr/bin/env python3
import json, os, pathlib, shutil, sys, time
a=sys.argv[1:]; cmd=a[0]; fault=os.getenv('FAKE_FAULT')
r=pathlib.Path(os.environ['FAKE_REMOTE'])
def p(v): return r/v.split(':',1)[1]
with open(os.environ['FAKE_LOG'],'a') as f: f.write(json.dumps(a)+'\\n')
if fault=='quota' and cmd=='copyto': sys.exit(7)
if fault=='hang' and cmd=='copyto': time.sleep(30)
if cmd=='config': print('type = drive' if fault=='crypt' else 'type = crypt')
elif cmd=='copyto':
 d=p(a[2]); d.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(a[1],d)
elif cmd=='size':
 v=p(a[1]); print(json.dumps({'count':1,'bytes':v.stat().st_size+(1 if fault=='size' else 0)}))
elif cmd=='cat':
 v=p(a[1]); data=v.read_bytes()
 if fault=='missing' and v.name.endswith('.spool.sqlite3.gz'): sys.exit(8)
 if fault=='readback' and v.name.endswith('.pair.json'): sys.exit(9)
 if fault=='hash' and v.name.endswith('.sql.gz'): data=bytes([data[0]^1])+data[1:]
 if fault=='partial' and v.name.endswith('.pair.json'): data=b'{}'
 sys.stdout.buffer.write(data)
elif cmd=='lsf':
 for v in p(a[1]).glob('*.pair.json'): print(v.name)
elif cmd=='deletefile':
 if fault=='retention': sys.exit(10)
 p(a[1]).unlink()
else: sys.exit(11)
""")
        script.chmod(0o700)
        self.log = self.root / "calls"
        self.remote = self.root / "remote"
        self.remote.mkdir(mode=0o700)
        self.environment = patch.dict(
            os.environ,
            PATH=str(self.bin) + ":" + os.environ["PATH"],
            FAKE_REMOTE=str(self.remote),
            FAKE_LOG=str(self.log),
            AVELREN_BACKUP_PASSWORD="secret-test-value",
        )
        self.environment.start()
        self.command_path = patch.object(
            self.module, "COMMAND_PATH", str(self.bin) + ":" + self.module.COMMAND_PATH
        )
        self.command_path.start()
        original_runner = state.run_bounded

        def fake_remote_boundary(argv, *, deadline, env=None, stdout_path=None):
            if argv[0] == "rclone":
                self.assertNotIn("AVELREN_BACKUP_PASSWORD", env)
                self.assertNotIn("PGPASSWORD", env)
                env = dict(
                    env,
                    FAKE_REMOTE=str(self.remote),
                    FAKE_LOG=str(self.log),
                    FAKE_FAULT=os.environ.get("FAKE_FAULT", ""),
                )
            return original_runner(argv, deadline=deadline, env=env, stdout_path=stdout_path)

        self.runner_boundary = patch.object(state, "run_bounded", fake_remote_boundary)
        self.runner_boundary.start()
        self.publisher = self.module.Publisher("crypt:paired", self.root / "config", self.root)

    def tearDown(self):
        self.runner_boundary.stop()
        self.command_path.stop()
        self.environment.stop()
        self.temp.cleanup()

    def make_pair(self, backup_id):
        runtime = Runtime([])
        sql = runtime.sql_snapshot(self.directory, backup_id, "unused")
        spool, summary = runtime.spool_snapshot(self.directory, backup_id, "unused")
        artifacts = {}
        for kind, path in [("sql", sql), ("spool", spool)]:
            sha = hashlib.sha256(path.read_bytes()).hexdigest()
            artifacts[kind] = dict(name=path.name, sha256=sha, bytes=path.stat().st_size)
            (self.directory / (path.name + ".sha256")).write_text(f"{sha}  {path.name}\n")
        times = {
            "sql": dict(started_at="2026-01-01T01:00:00Z", finished_at="2026-01-01T01:01:00Z"),
            "spool": dict(started_at="2026-01-01T01:02:00Z", finished_at="2026-01-01T01:03:00Z"),
        }
        manifest = self.module.pair.build_manifest(
            backup_id,
            artifacts,
            times,
            {k: v for k, v in IDENTITY.items() if k not in {"volume", "network"}},
            summary,
            True,
        )
        (self.directory / f"avelren-{backup_id}.pair.json").write_text(json.dumps(manifest))
        return manifest

    def test_real_bounded_rclone_publication_order_and_retention(self):
        tier = self.remote / "paired" / "daily"
        tier.mkdir(parents=True)
        legacy = tier / "avelren-20251014-010000.sql.gz"
        legacy.write_bytes(b"legacy")
        for day in range(2, 11):
            backup_id = f"202610{day:02}-010000"
            if day in {4}:  # Sunday belongs to weekly, not daily.
                continue
            value = self.make_pair(backup_id)
            if value["tier"] != "daily":
                continue
            for path in self.directory.glob(f"avelren-{backup_id}*"):
                shutil_copy = path.read_bytes()
                (tier / path.name).write_bytes(shutil_copy)
        value = self.make_pair("20261013-010000")
        self.publisher.preflight()
        self.publisher.deadline = time.monotonic() + 30
        paths = self.publisher.publish(value, self.directory)
        self.assertEqual(len(paths), 5)
        calls = [json.loads(line) for line in self.log.read_text().splitlines()]
        copies = [c for c in calls if c[0] == "copyto"]
        self.assertEqual(len(copies), 5)
        self.assertTrue(copies[-1][2].endswith(".pair.json"))
        marker = calls.index(copies[-1])
        self.assertGreater(sum(c[0] == "cat" for c in calls[:marker]), 3)
        self.assertEqual(len(list(tier.glob("*.pair.json"))), 7)
        self.assertTrue(legacy.exists())
        self.assertTrue((tier / "avelren-20261013-010000.pair.json").exists())
        self.assertNotIn("secret-test-value", self.log.read_text())
        # Reintroduce one verified overflow group; a real remote retention
        # failure must abort instead of silently granting acceptance.
        old_id = "20261002-010000"
        for path in self.directory.glob(f"avelren-{old_id}*"):
            (tier / path.name).write_bytes(path.read_bytes())
        with patch.dict(os.environ, FAKE_FAULT="retention"):
            self.publisher.deadline = time.monotonic() + 30
            with self.assertRaisesRegex(ValueError, "remote_operation_failed"):
                self.publisher.publish(value, self.directory)
        self.assertTrue(legacy.exists())
        self.assertTrue((tier / "avelren-20261013-010000.pair.json").exists())

    def test_faults_never_delete_or_return_acceptance(self):
        value = self.make_pair("20261013-010000")
        for fault in ["quota", "size", "missing", "hash", "readback", "partial"]:
            with self.subTest(fault=fault), patch.dict(os.environ, FAKE_FAULT=fault):
                self.publisher.deadline = time.monotonic() + 10
                with self.assertRaises(ValueError):
                    self.publisher.publish(value, self.directory)
                calls = self.log.read_text()
                self.assertNotIn('"deletefile"', calls)
                self.assertNotIn("secret-test-value", calls)

    def test_crypt_and_network_deadlines(self):
        with patch.dict(os.environ, FAKE_FAULT="crypt"):
            with self.assertRaisesRegex(ValueError, "crypt_required"):
                self.publisher.preflight()
        value = self.make_pair("20261013-010000")
        with patch.dict(os.environ, FAKE_FAULT="hang"):
            self.publisher.deadline = time.monotonic() + 0.15
            started = time.monotonic()
            with self.assertRaisesRegex(ValueError, "command_timeout"):
                self.publisher.publish(value, self.directory)
            self.assertLess(time.monotonic() - started, 2)

    def test_slow_publisher_hash_obeys_remaining_deadline(self):
        value = self.make_pair("20261013-010000")
        artifact = value["artifacts"]["sql"]
        local = self.directory / artifact["name"]
        target = self.remote / "paired" / "daily" / local.name
        target.parent.mkdir(parents=True)
        target.write_bytes(local.read_bytes())
        wrapper = self.root / "slow-python"
        wrapper.write_text(f'#!/bin/bash\nsleep 2\nexec "{sys.executable}" "$@"\n')
        wrapper.chmod(0o700)
        self.publisher.deadline = time.monotonic() + 0.8
        with patch.object(sys, "executable", str(wrapper)):
            started = time.monotonic()
            with self.assertRaisesRegex(ValueError, "command_timeout"):
                self.publisher.verify_file(local, "crypt:paired/daily/" + local.name)
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertEqual(list(self.root.glob(".local-*")), [])
        self.assertEqual(list(self.root.glob(".remote-*")), [])


if __name__ == "__main__":
    unittest.main()
