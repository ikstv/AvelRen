"""Cleanup test resources even on failure; never hide a cleanup failure."""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


class CleanupContract(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            "runtime_acceptance",
            Path(__file__).with_name("collector-runtime-daemon-test.py"),
        )
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def test_cleanup_failure_is_reported_after_other_resources(self):
        calls = []

        def run(args):
            calls.append(args)
            if args[1:3] == ["rm", "-f"]:
                raise AssertionError("synthetic cleanup failure")

        with (
            patch.object(self.module, "command", side_effect=run),
            self.assertRaises(AssertionError),
        ):
            self.module.cleanup_resources(
                ["a" * 64],
                "avelren-runtime-test-unit-spool",
                "avelren-runtime-test-unit-network",
            )
        self.assertEqual(len(calls), 3)

    def test_cleanup_rejects_production_resource(self):
        with patch.object(self.module, "command") as run, self.assertRaises(ValueError):
            self.module.cleanup_resources(
                [], "avelren_collector_spool_v1", "avelren_default"
            )
        run.assert_not_called()

    def test_cleanup_does_not_delete_uncreated_resources(self):
        with patch.object(self.module, "command") as run:
            self.module.cleanup_resources([], None, None)
        run.assert_not_called()

    def test_new_rollback_cycle_must_be_captured_and_acknowledged(self):
        snapshots = iter([
            {"calls": [1, 2], "status": {"pending_count": 0, "acked_count": 2}},
            # Transport has logged a new request, but spool.finish has not run.
            {"calls": [1, 2, 3], "status": {"pending_count": 0, "acked_count": 2}},
            {"calls": [1, 2, 3], "status": {"pending_count": 1, "acked_count": 2}},
            {"calls": [1, 2, 3], "status": {"pending_count": 0, "acked_count": 3}},
        ])

        def wait(predicate, seconds):
            self.assertEqual(seconds, 90)
            self.assertFalse(predicate())
            self.assertFalse(predicate())
            self.assertFalse(predicate())
            self.assertTrue(predicate())

        with patch.object(self.module, "wait", side_effect=wait):
            self.module.wait_for_replayed_cycle(lambda: next(snapshots), 2)


if __name__ == "__main__":
    unittest.main()
