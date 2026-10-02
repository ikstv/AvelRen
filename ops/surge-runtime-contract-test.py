"""Контракт із реальним Compose parser, без запуску служб чи доступу до production."""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SurgeRuntimeContract(unittest.TestCase):
    def model(self, *args):
        env = os.environ.copy()
        env.pop("COMPOSE_PROFILES", None)
        with tempfile.TemporaryDirectory() as directory:
            empty = Path(directory) / "empty.env"
            empty.write_bytes(b"")
            result = subprocess.run(
                [
                    "docker",
                    "compose",
                    "--env-file",
                    str(empty),
                    "-f",
                    str(ROOT / "docker-compose.yml"),
                    *args,
                    "config",
                    "--no-interpolate",
                    "--format",
                    "json",
                ],
                check=False,
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_worker_profile_and_isolation(self):
        services = self.model("--profile", "surge")["services"]
        self.assertIn("surge_worker", services, "profile lacks surge worker")
        worker = services["surge_worker"]
        self.assertEqual(worker["profiles"], ["surge"])
        self.assertEqual(worker["command"], ["python", "-m", "avelren.surge_worker"])
        self.assertEqual(
            worker["environment"]["DATABASE_URL"], "${AVELREN_SURGE_DSN:-}"
        )
        self.assertEqual(
            set(worker["environment"]), {"DATABASE_URL", "SURGE_ENABLED", "LOG_LEVEL"}
        )
        self.assertEqual(worker["restart"], "on-failure:3")
        self.assertFalse(worker.get("volumes"))
        self.assertFalse(worker.get("ports"))
        self.assertFalse(worker.get("privileged", False))
        self.assertEqual(worker["cap_drop"], ["ALL"])
        self.assertIn("no-new-privileges:true", worker["security_opt"])
        self.assertNotIn("surge_worker", services["collector"].get("depends_on", {}))
        self.assertNotIn("collector", worker.get("depends_on", {}))

    def test_kill_switch_defaults_off_every_consumer(self):
        services = self.model("--profile", "surge")["services"]
        for name in ("api", "notifier", "surge_worker"):
            with self.subTest(service=name):
                self.assertEqual(
                    services.get(name, {}).get("environment", {}).get("SURGE_ENABLED"),
                    "${SURGE_ENABLED:-false}",
                )

    def test_default_start_excludes_worker_and_migrations(self):
        env = os.environ.copy()
        env.pop("COMPOSE_PROFILES", None)
        result = subprocess.run(
            [
                "docker",
                "compose",
                "--env-file",
                str(ROOT / ".env.example"),
                "-f",
                str(ROOT / "docker-compose.yml"),
                "config",
                "--services",
            ],
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("surge_worker", result.stdout.splitlines())
        self.assertNotIn("migrate", result.stdout.splitlines())


if __name__ == "__main__":
    unittest.main()
