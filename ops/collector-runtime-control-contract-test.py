"""Контракт операторського control із фіктивним Docker та годинником."""

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def module():
    path = Path(__file__).with_name("collector-runtime-control.py")
    spec = importlib.util.spec_from_file_location("runtime_control", path)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


class ControlContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.manifest = {
            "state_dir": self.temp.name,
            "container_name": "avelren-runtime-test-control",
            "project": "avelren-runtime-test-control",
            "compose_file": "/test/compose.yml",
            "env_file": "/test/private.env",
            "image_id": "sha256:" + "a" * 64,
            "source_commit": "b" * 40,
            "network": "avelren-runtime-test-network",
            "volume": "avelren-runtime-test-volume",
        }
        self.target = {
            "Id": "c" * 64,
            "Image": self.manifest["image_id"],
            "RestartCount": 0,
            "State": {"Running": True},
        }
        self.trace = []

    def invoke(self, action, *, fail=False, interrupted=False, mode="on"):
        obj = module()

        def preflight(value, **kw):
            self.trace.append("guard")
            if fail:
                raise ValueError("second_poller")
            return value, self.target

        def run(args, **kw):
            self.trace.append(args)
            if "stop" in args:
                self.target["State"]["Running"] = False
            if "start" in args:
                self.target["State"]["Running"] = True
            if "avelren.collector_control" in args:
                return json.dumps(
                    {"capture_only": mode == "on", "mode_ack": mode == "on"}
                )
            return ""

        def delay(seconds):
            self.trace.append(("wait", seconds))
            if interrupted:
                raise KeyboardInterrupt

        with (
            patch.object(obj.runtime, "preflight", side_effect=preflight),
            patch.object(obj.runtime, "run", side_effect=run),
            patch.object(obj, "wait_interval", side_effect=delay),
        ):
            return obj.execute(
                self.manifest, action, [mode] if action == "capture-only" else []
            )

    def test_second_poller(self):
        with self.assertRaises(ValueError):
            self.invoke("restart", fail=True)
        self.assertEqual(self.trace, ["guard"])

    def test_stop_start_delay(self):
        self.invoke("stop")
        self.invoke("start")
        self.assertIn(("wait", 60), self.trace)
        state = json.loads((Path(self.temp.name) / "stop.json").read_text())
        self.assertEqual(state["container_id"], self.target["Id"])

    def test_restart_delay(self):
        self.invoke("restart")
        actions = [x for x in self.trace if isinstance(x, list)]
        self.assertTrue(any("stop" in a for a in actions))
        self.assertTrue(any("start" in a for a in actions))
        self.assertFalse(any("up" in a or "restart" in a for a in actions))
        self.assertIn(("wait", 60), self.trace)
        self.assertTrue(all(a[-1] == "collector" for a in actions))

    def test_signal_after_stop(self):
        with self.assertRaises(KeyboardInterrupt):
            self.invoke("restart", interrupted=True)
        self.assertFalse(self.target["State"]["Running"])
        self.assertTrue((Path(self.temp.name) / "stop.json").exists())
        self.assertFalse(any(isinstance(x, list) and "start" in x for x in self.trace))

    def test_missing_state(self):
        self.target["State"]["Running"] = False
        self.invoke("start")
        self.assertIn(("wait", 60), self.trace)

    def test_backward_clock(self):
        (Path(self.temp.name) / "stop.json").write_text('{"stopped_at":99999999999}')
        self.target["State"]["Running"] = False
        self.invoke("start")
        self.assertIn(("wait", 60), self.trace)

    def test_capture_ack(self):
        result = self.invoke("capture-only")
        self.assertTrue(result["mode_ack"])

    def test_capture_timeout(self):
        obj = module()
        with (
            patch.object(
                obj.runtime, "preflight", return_value=(self.manifest, self.target)
            ),
            patch.object(obj.runtime, "run", side_effect=ValueError("command_failed")),
            self.assertRaises(ValueError),
        ):
            obj.execute(self.manifest, "capture-only", ["on"])

    @unittest.skipUnless(os.name == "posix", "real flock proof runs in Linux container")
    def test_concurrent_lock(self):
        obj = module()
        with (
            obj.operator_lock(Path(self.temp.name)),
            self.assertRaisesRegex(ValueError, "operator_busy"),
            obj.operator_lock(Path(self.temp.name)),
        ):
            self.fail("second operator acquired lock")

    def test_capture_wrong_ack(self):
        obj = module()
        with (
            patch.object(
                obj.runtime, "preflight", return_value=(self.manifest, self.target)
            ),
            patch.object(
                obj.runtime,
                "run",
                return_value='{"capture_only":true,"mode_ack":false}',
            ),
            self.assertRaisesRegex(ValueError, "capture_mode_not_acknowledged"),
        ):
            obj.execute(self.manifest, "capture-only", ["on"])


if __name__ == "__main__":
    unittest.main()
