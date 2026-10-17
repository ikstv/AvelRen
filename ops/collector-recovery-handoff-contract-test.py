"""Контракти CAS handoff без Docker та запитів до джерела."""

import copy
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "handoff", Path(__file__).with_name("collector-recovery-handoff.py")
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Adapter:
    def __init__(self):
        self.record = {
            "generation": "generation",
            "phase": "recovery_required",
            "identity": {"id": "old"},
        }
        self.journal = None
        self.events = []
        self.current = {"id": "old"}
        self.running = True
        self.pending = 0
        self.ack = False
        self.fail = None

    def read(self):
        return copy.deepcopy(self.record)

    def journal_read(self):
        return copy.deepcopy(self.journal)

    def journal_save(self, expected, value):
        if expected != self.journal:
            raise ValueError("journal_changed")
        self.journal = copy.deepcopy(value)

    def state_save(self, expected, value):
        if expected != self.record:
            raise ValueError("state_changed")
        self.record = copy.deepcopy(value)

    def validate(self, expected, journal=None):
        allowed = [expected]
        if journal and journal["phase"] in {
            "state_intent",
            "terminal_intent",
            "rollback_state_intent",
        }:
            allowed.append(journal["next_state"])
        if self.record not in allowed:
            raise ValueError("state_changed")

    def preflight(self):
        return {"generation": "generation", "old": {"id": "old"}, "new": {"id": "new"}}

    def cleanup(self):
        self.events.append("cleanup")

    def stop(self, identity):
        if self.current != identity:
            raise ValueError("identity_changed")
        self.running = False
        self.events.append("stop")

    def safety(self):
        if self.fail == "safety":
            raise ValueError("safety_failed")
        self.events.append("safety")
        return {"sql": "hash", "spool": "hash", "rollback": "hash"}

    def switch(self, manifest):
        self.events.append("switch")
        self.current = copy.deepcopy(manifest)

    def wait(self):
        self.events.append("wait60")

    def start(self):
        self.running = True
        self.events.append("start")
        return self.current

    def identity(self):
        return self.current

    def off(self):
        self.events.append("off")
        return {"capture_only": False, "mode_ack": self.ack, "pending_count": self.pending}

    def backlog(self):
        return {"pending": self.pending, "started": 0}


class Contracts(unittest.TestCase):
    def run_flow(self, adapter):
        module.Handoff(adapter).prepare()
        module.Handoff(adapter).switch()
        return module.Handoff(adapter).finish()

    def test_switch_rejects_unpinned_identity_before_mutation(self):
        a = Adapter()
        module.Handoff(a).prepare()
        a.current = {"id": "foreign"}
        with self.assertRaisesRegex(ValueError, "identity_changed"):
            module.Handoff(a).switch()
        self.assertNotIn("switch", a.events)

    def test_rollback_rejects_unpinned_identity_before_stop(self):
        a = Adapter()
        module.Handoff(a).prepare()
        module.Handoff(a).switch()
        a.current = {"id": "foreign"}
        before = list(a.events)
        with self.assertRaisesRegex(ValueError, "identity_changed"):
            module.Handoff(a).rollback()
        self.assertEqual(a.events, before)

    def test_helper_inventory_only_accepts_journal_pinned_runtime_ids(self):
        a = module.LocalAdapter.__new__(module.LocalAdapter)
        old, new = {"id": "old"}, {"id": "new"}
        value = {"generation": "generation", "identity": old}
        a.read = lambda: value
        a.journal_read = lambda: {"new_identity": new}

        def item(identity):
            return {
                "Name": "/avelren-paired-generation-handoff-status",
                "Config": {
                    "Labels": {
                        "org.avelren.backup.generation": "generation",
                        "org.avelren.backup.runtime": module.hashlib.sha256(
                            module.json.dumps(identity, sort_keys=True).encode()
                        ).hexdigest(),
                    }
                },
                "State": {"Running": False},
                "HostConfig": {"RestartPolicy": {"Name": "no"}},
            }

        inventory = [item(new)]
        a.control = SimpleNamespace(runtime=SimpleNamespace(inspect_inventory=lambda: inventory))
        a.jobs(remove=False)
        inventory[:] = [item({"id": "foreign"})]
        with self.assertRaisesRegex(ValueError, "foreign_ambiguous_or_live_job"):
            a.jobs(remove=False)
        inventory[:] = [item(new)]
        inventory[0]["State"]["Running"] = True
        with self.assertRaisesRegex(ValueError, "foreign_ambiguous_or_live_job"):
            a.jobs(remove=False)

    def test_requested_compose_manifest_is_bound_during_sanitized_output(self):
        a = module.LocalAdapter.__new__(module.LocalAdapter)
        seen = []
        a.runtime = SimpleNamespace(manifest={"image_id": "old"})
        a.runtime.output = lambda argv, env=None: seen.append(a.runtime.manifest) or "{}"
        requested = {"image_id": "new"}
        self.assertEqual(a.compose_output(requested, ["docker", "compose"], {}), "{}")
        self.assertEqual(seen, [requested])
        self.assertEqual(a.runtime.manifest, {"image_id": "old"})

    def test_dry_run_sanitization_binds_requested_candidate(self):
        a = module.LocalAdapter.__new__(module.LocalAdapter)
        old = dict(compose_file="/fixture/compose.yml", image_id="old")
        new = dict(old, image_id="new")
        a.current = old
        seen = []
        a.paired = SimpleNamespace(command_environment=lambda **kw: kw)
        a.runtime = SimpleNamespace(manifest=old, output=a.read_only_output)

        def run(argv, **kwargs):
            seen.append(kwargs["env"])
            return SimpleNamespace(returncode=0, stdout="{}")

        with patch.object(module.subprocess, "run", side_effect=run):
            a.compose_output(new, ["docker", "-f", old["compose_file"], "config"], {})
        self.assertEqual(seen[0]["collector"], new)
        self.assertEqual(a.runtime.manifest, old)

    def test_backlog_keeps_database_read_only_but_allows_wal_coordination(self):
        a = module.LocalAdapter.__new__(module.LocalAdapter)
        a.work = Path("/fixture")
        a.old, a.new = {"volume": "volume"}, {"image_id": "new"}

        def job(kind, image, options, command, output):
            self.assertNotIn("readonly", " ".join(options))
            self.assertIn("mode=ro", command[-1])

        a.runtime = SimpleNamespace(job=job, cancel_jobs=lambda kinds: True)
        with patch.object(Path, "read_text", return_value="{}"):
            self.assertEqual(a.backlog(), {"pending": 0, "started": 0})

    def test_normal_and_no_forged_publication(self):
        a = Adapter()
        result = self.run_flow(a)
        self.assertEqual(result["phase"], "resumed")
        self.assertEqual(
            a.events, ["cleanup", "stop", "safety", "switch", "wait60", "start", "off"]
        )
        self.assertEqual(a.journal["phase"], "complete")
        self.assertEqual(a.journal["old_state"]["identity"], {"id": "old"})

    def test_drift_refused_before_stop(self):
        a = Adapter()
        h = module.Handoff(a)
        h.prepare()
        a.record["phase"] = "published"
        with self.assertRaises(ValueError):
            h.switch()
        self.assertNotIn("start", a.events)

    def test_safety_failure_never_starts(self):
        a = Adapter()
        a.fail = "safety"
        with self.assertRaises(ValueError):
            module.Handoff(a).prepare()
        self.assertFalse(a.running)
        self.assertNotIn("start", a.events)
        a.fail = None
        module.Handoff(a).prepare()
        module.Handoff(a).switch()
        self.assertIn("start", a.events)

    def test_missing_native_ack_leaves_interlock(self):
        a = Adapter()
        a.ack = None
        with self.assertRaises(ValueError):
            self.run_flow(a)
        self.assertNotEqual(a.journal["phase"], "complete")
        self.assertEqual(a.record["phase"], "off_intent")
        a.ack = False
        module.Handoff(a).finish()
        self.assertEqual(a.record["phase"], "resumed")

    def test_reverse_handoff_refuses_started_or_unproven_backlog(self):
        for counts in (
            {"pending": 0, "started": 1},
            {"pending": 0},
            {"pending": 0, "started": None},
        ):
            with self.subTest(counts=counts):
                a = Adapter()
                module.Handoff(a).prepare()
                module.Handoff(a).switch()
                a.backlog = lambda counts=counts: counts
                before = len(a.events)
                with self.assertRaisesRegex(ValueError, "legacy_rollback_backlog"):
                    module.Handoff(a).rollback()
                self.assertFalse(a.running)
                self.assertNotIn("switch", a.events[before:])
                self.assertNotIn("start", a.events[before:])
                self.assertEqual(a.journal["phase"], "rollback_intent")
                self.assertNotIn(a.journal["phase"], module.TERMINAL)

    def test_reverse_handoff_requires_empty_backlog(self):
        a = Adapter()
        module.Handoff(a).prepare()
        module.Handoff(a).switch()
        a.pending = 1
        with self.assertRaises(ValueError):
            module.Handoff(a).rollback()
        self.assertFalse(a.running)
        a.pending = 0
        module.Handoff(a).rollback()
        self.assertEqual(a.current, {"id": "old"})
        self.assertEqual(a.record["phase"], "recovery_required")
        self.assertEqual(a.events[-3:], ["stop", "wait60", "start"])

    def test_process_death_after_every_persistent_or_external_mutation(self):
        class Crash(BaseException):
            pass

        class Fault(Adapter):
            count = 0
            crash_at = None

            def event(self):
                self.count += 1
                if self.count == self.crash_at:
                    raise Crash()

            def journal_save(self, expected, value):
                super().journal_save(expected, value)
                self.event()

            def state_save(self, expected, value):
                super().state_save(expected, value)
                self.event()

            def stop(self, identity):
                super().stop(identity)
                self.event()

            def safety(self):
                result = super().safety()
                self.event()
                return result

            def switch(self, manifest):
                super().switch(manifest)
                self.event()

            def start(self):
                result = super().start()
                self.event()
                return result

            def off(self):
                result = super().off()
                self.event()
                return result

        baseline = Fault()
        self.run_flow(baseline)
        for mutation in range(1, baseline.count + 1):
            with self.subTest(mutation=mutation):
                a = Fault()
                a.crash_at = mutation
                try:
                    self.run_flow(a)
                except Crash:
                    pass
                a.crash_at = None
                phase = a.journal["phase"] if a.journal else None
                # New state-machine instance models a process restart; durable
                # adapter state and observed daemon survive it.
                if phase in (None, "stop_intent"):
                    module.Handoff(a).prepare()
                if phase == "switch_intent" and a.current != a.journal["old_state"]["identity"]:
                    with self.assertRaisesRegex(ValueError, "identity_changed"):
                        module.Handoff(a).switch()
                    self.assertFalse(a.running)
                    continue
                if a.journal["phase"] in ("prepared", "switch_intent", "start_intent"):
                    module.Handoff(a).switch()
                module.Handoff(a).finish()
                self.assertEqual(a.record["phase"], "resumed")
                self.assertEqual(a.journal["phase"], "complete")

    def test_reverse_identity_and_terminal_write_crashes(self):
        class Crash(BaseException):
            pass

        for operation in ("switch", "start", "state_save", "journal_save"):
            with self.subTest(operation=operation):
                a = Adapter()
                module.Handoff(a).prepare()
                module.Handoff(a).switch()
                original = getattr(a, operation)
                armed = [True]

                def interrupted(*args, original=original, armed=armed, **kwargs):
                    result = original(*args, **kwargs)
                    # First journal mutation is rollback_intent; interruption
                    # still tests resuming durable reverse intent.
                    if armed[0]:
                        armed[0] = False
                        raise Crash()
                    return result

                setattr(a, operation, interrupted)
                with self.assertRaises(Crash):
                    module.Handoff(a).rollback()
                if operation == "switch":
                    with self.assertRaisesRegex(ValueError, "identity_changed"):
                        module.Handoff(a).rollback()
                    self.assertFalse(a.running)
                    continue
                module.Handoff(a).rollback()
                self.assertEqual(a.journal["phase"], "rolled_back")
                self.assertEqual(a.record["identity"], {"id": "old"})


@unittest.skipUnless(sys.platform == "linux", "Linux fsync/flock/proc contracts")
class FilesystemContracts(unittest.TestCase):
    def setUp(self):
        self.state = module.load("paired_backup_state", "paired_backup_state.py")
        self.fixture = module.load("handoff_state_fixture", "paired-backup-state-contract-test.py")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.a = module.LocalAdapter.__new__(module.LocalAdapter)
        self.a.directory = self.directory
        self.a.state = self.state
        self.a.control = SimpleNamespace(runtime=SimpleNamespace(private_path=lambda p: None))

    def test_atomic_journal_requires_real_lease_and_interlocks_coordinators(self):
        with self.assertRaises(ValueError):
            self.a.journal_save(None, {"phase": "prepared"})
        with self.state.backup_lock(self.directory):
            value = {"format_version": 1, "phase": "prepared"}
            self.a.journal_save(None, value)
            self.assertEqual(self.a.journal_read(), value)
            with self.assertRaisesRegex(ValueError, "collector_handoff_required"):
                self.state.assert_no_handoff(self.directory)
            with self.assertRaisesRegex(ValueError, "journal_changed"):
                self.a.journal_save(None, value)
            self.a.journal_save(value, dict(value, phase="complete"))
            self.state.assert_no_handoff(self.directory)

    def test_symlink_and_hardlink_journal_are_never_overwritten(self):
        target = self.directory / "target"
        target.write_text("{}")
        target.chmod(0o600)
        path = self.directory / module.JOURNAL
        for link in (lambda: path.symlink_to(target), lambda: os.link(target, path)):
            link()
            with self.state.backup_lock(self.directory):
                with self.assertRaises((ValueError, OSError)):
                    self.a.journal_save(None, {"phase": "prepared"})
            path.unlink()
            self.assertEqual(target.read_text(), "{}")

    def test_real_proc_rejects_live_reused_and_other_boot_owners(self):
        dead = self.fixture.record()["owner"]
        self.assertTrue(self.state._owner_dead(dead))
        live = self.state.process_identity(os.getpid())
        self.assertFalse(self.state._owner_dead(live))
        self.assertFalse(self.state._owner_dead(dict(live, start_ticks=live["start_ticks"] + 1)))
        self.assertFalse(
            self.state._owner_dead(dict(dead, boot_id="11111111-1111-4111-8111-111111111111"))
        )

    def test_resumed_adapter_revalidates_owner_children_and_file_pins(self):
        old = self.fixture.record("recovery_required")
        manifest = self.directory / "manifest.json"
        candidate = self.directory / "candidate.json"
        manifest.write_text("{}")
        candidate.write_text("{}")
        self.a.args = SimpleNamespace(
            manifest=manifest,
            new_manifest=candidate,
            manifest_sha256=module.digest(manifest),
            new_manifest_sha256=module.digest(candidate),
        )
        self.a.bound_files = {}
        self.a.old = {}
        self.a.jobs = lambda **kwargs: None
        with self.state.backup_lock(self.directory):
            self.state.write_state(self.directory, old)
            self.a.validate(old)
            for owner in (
                self.state.process_identity(os.getpid()),
                dict(old["owner"], boot_id="11111111-1111-4111-8111-111111111111"),
            ):
                changed = dict(old, owner=owner)
                self.state.write_state(self.directory, changed)
                with self.assertRaisesRegex(ValueError, "owner_unproven"):
                    self.a.validate(changed)
            child = dict(old, children=[self.state.process_identity(os.getpid())])
            self.state.write_state(self.directory, child)
            with self.assertRaisesRegex(ValueError, "child_unproven"):
                self.a.validate(child)
            self.state.write_state(self.directory, old)
            candidate.write_text('{"drift":true}')
            with self.assertRaisesRegex(ValueError, "new_manifest_changed"):
                self.a.validate(old)

    def test_stopped_wal_read_only_sql_needs_writable_coordination_directory(self):
        self.directory.chmod(0o755)
        spool = self.directory / "spool"
        spool.mkdir(mode=0o700)
        os.chown(spool, 10001, 10001)
        database = spool / "cycles.sqlite3"

        def run(code):
            return module.subprocess.run(
                [sys.executable, "-c", code],
                preexec_fn=lambda: os.setuid(10001),
                capture_output=True,
                text=True,
            )

        setup = (
            "import sqlite3; c=sqlite3.connect("
            + repr(str(database))
            + "); c.execute('pragma journal_mode=wal'); "
            "c.execute('create table cycles(state text)'); "
            "c.execute(\"insert into cycles values ('pending')\"); c.commit(); c.close()"
        )
        self.assertEqual(run(setup).returncode, 0)
        query = (
            "import sqlite3; c=sqlite3.connect("
            + repr("file:" + str(database) + "?mode=ro")
            + ",uri=True); print(c.execute('select count(*) from cycles').fetchone()[0])"
        )
        spool.chmod(0o500)
        denied = run(query)
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn("readonly database", denied.stderr)
        spool.chmod(0o700)
        allowed = run(query)
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        self.assertEqual(allowed.stdout.strip(), "1")
        denied_write = run(query + "; c.execute('delete from cycles')")
        self.assertNotEqual(denied_write.returncode, 0)
        self.assertIn("readonly database", denied_write.stderr)

    def test_actual_runtime_sanitization_receives_requested_compose_image(self):
        paired = module.load("handoff_paired_env_test", "paired-backup.py")
        runtime = paired.Runtime.__new__(paired.Runtime)
        runtime.work = self.directory
        runtime.deadline = 123
        old = dict(
            compose_file="/fixture/compose.yml",
            image_id="old",
            env_file="/fixture/env",
            container_name="collector",
            network="network",
            volume="volume",
        )
        new = dict(old, image_id="new")
        runtime.manifest = old
        self.a.runtime = runtime
        seen = []

        def run(argv, *, deadline, stdout_path, env):
            seen.append(env)
            stdout_path.write_text("{}")
            return 0

        with patch.object(paired.state, "run_bounded", side_effect=run):
            self.a.compose_output(
                new,
                ["docker", "compose", "-f", old["compose_file"], "config"],
                {"UNTRUSTED": "ignored"},
            )
        self.assertEqual(seen[0]["COLLECTOR_IMAGE_ID"], "new")
        self.assertNotIn("UNTRUSTED", seen[0])
        self.assertEqual(runtime.manifest, old)

    def test_safety_artifacts_are_reopened_before_handoff_mutations(self):
        import gzip

        self.a.work = self.directory
        capture = self.directory / "safety-test"
        capture.mkdir(mode=0o700)
        files = {
            "sql": capture / "avelren-safety.sql.gz",
            "spool": capture / "avelren-safety.spool.sqlite3.gz",
            "rollback": capture / "rollback.json",
        }
        for kind, path in files.items():
            path.write_bytes(b"{}" if kind == "rollback" else gzip.compress(b"payload"))
            path.chmod(0o600)
        safety = dict(directory=str(capture), **{k: module.digest(v) for k, v in files.items()})
        self.a.verify_safety(safety)
        for path in files.values():
            original = path.read_bytes()
            path.unlink()
            with self.assertRaises((ValueError, OSError)):
                self.a.verify_safety(safety)
            path.write_bytes(b"corrupt")
            path.chmod(0o600)
            with self.assertRaises(ValueError):
                self.a.verify_safety(safety)
            path.write_bytes(original)
        self.a.verify_safety(safety)

    def test_state_write_crash_readback_accepts_exact_replacement(self):
        old = self.fixture.record("recovery_required")
        replacement = dict(old, phase="resumed")
        with self.state.backup_lock(self.directory):
            self.state.write_state(self.directory, old)
            self.a.state_save(old, replacement)
            self.assertEqual(self.a.read(), replacement)
            with self.assertRaisesRegex(ValueError, "state_changed"):
                self.a.state_save(old, replacement)


if __name__ == "__main__":
    unittest.main()
