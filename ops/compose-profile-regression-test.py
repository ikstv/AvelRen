"""Перевірка profile guard із реальним Compose, без daemon чи служб."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = r'''#!/usr/bin/env python3
import os, signal, subprocess, sys, time
signal.signal(signal.SIGPIPE, signal.SIG_DFL)
args = sys.argv[1:]
assert args[0] == "compose" and "config" in args, args
binary = os.environ.get("COMPOSE_TEST_BINARY")
command = [binary, *args[1:]] if binary else [os.environ["REAL_DOCKER"], *args]
result = subprocess.run(command, capture_output=True)
sys.stderr.buffer.write(result.stderr)
if "--services" in args and os.environ.get("FAIL_SERVICES") == "1":
    sys.stdout.write("migrate\n")
    sys.exit(42)
if "--services" in args and result.returncode == 0:
    # Реальний список, але окремі записи надходять різними write().
    # grep -q закриває pipe після migrate, хоча Compose ще пише решту.
    for line in result.stdout.splitlines(keepends=True):
        sys.stdout.buffer.write(line)
        sys.stdout.buffer.flush()
        time.sleep(0.03)
else:
    sys.stdout.buffer.write(result.stdout)
sys.exit(result.returncode)
'''


class ProfileGuardTest(unittest.TestCase):
    def run_contract(self, transform=lambda text: text, fail_services=False):
        with tempfile.TemporaryDirectory(prefix="avelren-profile-test-") as directory:
            root = Path(directory)
            (root / "ops").mkdir()
            (root / "bin").mkdir()
            shutil.copy2(ROOT / "ops/compose-production-contract-test.sh", root / "ops")
            (root / "docker-compose.yml").write_text(
                transform((ROOT / "docker-compose.yml").read_text()), encoding="utf-8"
            )
            wrapper = root / "bin/docker"
            wrapper.write_text(WRAPPER, encoding="utf-8")
            wrapper.chmod(0o755)
            env = os.environ.copy()
            env.pop("COMPOSE_PROFILES", None)
            env["REAL_DOCKER"] = shutil.which("docker") or "docker"
            env["PATH"] = str(root / "bin") + os.pathsep + env["PATH"]
            env["FAIL_SERVICES"] = "1" if fail_services else "0"
            return subprocess.run(
                ["bash", str(root / "ops/compose-production-contract-test.sh")],
                cwd=root, env=env, capture_output=True, text=True, timeout=60,
            )

    def test_valid_model_with_streamed_service_output(self):
        result = self.run_contract()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("compose security contract ok", result.stdout)

    def test_failed_compose_is_not_accepted_as_service_list(self):
        result = self.run_contract(fail_services=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("service discovery failed", result.stderr)

    def test_migrate_must_not_enter_default_services(self):
        result = self.run_contract(lambda text: text.replace('profiles: ["migrate"]', 'profiles: []'))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("migrate is in the default service set", result.stderr)

    def test_migrate_profile_must_reach_service(self):
        result = self.run_contract(lambda text: text.replace('profiles: ["migrate"]', 'profiles: ["other"]'))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("migrate is not reachable", result.stderr)


if __name__ == "__main__":
    unittest.main()
