import hashlib
import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "handoff_daemon", Path(__file__).with_name("collector-recovery-handoff-daemon-test.py")
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class Contracts(unittest.TestCase):
    def test_captured_historical_dependencies_are_exact_and_fixture_scoped(self):
        root = Path(__file__).parents[1]
        fixtures = root / "ops/eta-legacy-hotfix/fixtures"
        for filename, expected in {
            "db.py": "4e3f40271e64d943de02a3f8e53200185afef97e195c349937b60ef3eb691309",
            "models.py": "1aa2cb96c8fec9dc7e67d5759c97fcebc732ae67060643c99848df2571acd2ae",
        }.items():
            self.assertEqual(
                hashlib.sha256((fixtures / filename).read_bytes()).hexdigest(), expected
            )
        driver = (root / "ops/paired-backup-daemon-test.py").read_text()
        self.assertIn("legacy_modules =", driver)
        self.assertIn('legacy_proof["modules"]', driver)
        self.assertIn('assert legacy_proof["synthetic_loaded"]', driver)
        migration = (root / "ops/collector-spool-migration-test.py").read_text()
        self.assertIn('row["wait_time_status"] != "legacy_unknown"', migration)

    def test_real_fixture_runs_handoff_before_first_modern_cycle(self):
        source = Path(__file__).with_name("paired-backup-daemon-test.py").read_text()
        self.assertIn("handoff_daemon.run(", source)
        self.assertIn("Dockerfile.legacy-collector", source)
        self.assertLess(
            source.index("handoff_daemon.run("), source.index("wait first real producer cycle")
        )

    def test_sigkill_observes_incomplete_native_wait(self):
        source = Path(__file__).with_name("collector-recovery-handoff-daemon-test.py").read_text()
        self.assertIn("adapter.wait = announce_wait", source)
        self.assertIn('adapter.journal_read()["phase"] == "start_intent"', source)
        self.assertIn('assert not adapter.target()["State"]["Running"]', source)
        self.assertLess(
            source.index('os.write(write_fd, b"waiting")'), source.index("native_wait()")
        )
        self.assertIn("h.Handoff(adapter).rollback()", source)
        self.assertIn("args.state_sha256 = h.digest", source)

    def test_native_interval_and_ack(self):
        good = dict(capture_only=False, mode_ack=False, pending_count=0)
        m.assert_native_transition(1, 61, good)
        for bad in (
            dict(good, mode_ack=None),
            dict(good, pending_count=1),
            dict(good, capture_only=True),
        ):
            with self.assertRaises(AssertionError):
                m.assert_native_transition(1, 61, bad)
        with self.assertRaises(AssertionError):
            m.assert_native_transition(1, 60.99, good)


if __name__ == "__main__":
    unittest.main()
