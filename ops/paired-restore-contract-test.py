"""Fail-closed paired reader and public rehearsal boundary contracts."""

import gzip
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from paired_backup_manifest import ManifestError, build_manifest

ROOT = Path(__file__).resolve().parents[1]
STAMP = "20261013-090000"
NAME = f"avelren-{STAMP}.pair.json"


def reader():
    spec = importlib.util.spec_from_file_location(
        "paired_reader", ROOT / "ops/paired-restore-acceptance.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReaderContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def pair(self):
        spool = b"not a sqlite database"
        artifacts = {}
        for key, suffix, raw in [
            ("sql", ".sql.gz", b"SELECT 1;"),
            ("spool", ".spool.sqlite3.gz", spool),
        ]:
            name = f"avelren-{STAMP}{suffix}"
            data = gzip.compress(raw)
            digest = hashlib.sha256(data).hexdigest()
            (self.directory / name).write_bytes(data)
            (self.directory / (name + ".sha256")).write_text(f"{digest}  {name}\n")
            artifacts[key] = {"name": name, "sha256": digest, "bytes": len(data)}
        self.manifest = build_manifest(
            STAMP,
            artifacts,
            {
                "sql": {
                    "started_at": "2026-10-13T09:00:00+00:00",
                    "finished_at": "2026-10-13T09:00:01+00:00",
                },
                "spool": {
                    "started_at": "2026-10-13T09:00:02+00:00",
                    "finished_at": "2026-10-13T09:00:03+00:00",
                },
            },
            {
                "source_commit": "a" * 40,
                "image_id": "sha256:" + "b" * 64,
                "container_id": "c" * 64,
                "restart_count": 0,
                "started_at": "2026-10-13T08:00:00+00:00",
            },
            {
                "schema_version": 1,
                "payload_version": 1,
                "state_counts": {"started": 0, "pending": 0, "acked": 0},
                "payload_count": 0,
                "cycle_range": dict.fromkeys(["first_seq", "last_seq", "first_at", "last_at"]),
                "sha256": hashlib.sha256(spool).hexdigest(),
                "bytes": len(spool),
            },
            True,
        )
        self.save()

    def save(self):
        (self.directory / NAME).write_text(json.dumps(self.manifest))

    def reject(self, name=NAME):
        before = {p.name: p.read_bytes() for p in self.directory.iterdir() if p.is_file()}
        with self.assertRaises(ManifestError):
            reader().read_pair(self.directory, name, self.directory / "owned")
        self.assertEqual(
            before, {p.name: p.read_bytes() for p in self.directory.iterdir() if p.is_file()}
        )
        self.assertFalse((self.directory / "owned").exists())

    def test_manifest_basename_escape_and_legacy_refused(self):
        for name in ("../pair.json", "/pair.json", "C:\\pair.json", "legacy.sql.gz"):
            self.reject(name)

    def test_missing_completion_refused(self):
        self.reject()

    def test_incomplete_pair_refused(self):
        self.pair()
        (self.directory / self.manifest["artifacts"]["spool"]["name"]).unlink()
        self.reject()

    def test_mixed_id_refused(self):
        self.pair()
        self.manifest["artifacts"]["spool"]["name"] = "avelren-20261012-090000.spool.sqlite3.gz"
        self.save()
        self.reject()

    def test_duplicate_json_key_refused(self):
        self.pair()
        path = self.directory / NAME
        path.write_text(
            path.read_text().replace(
                '"format_version": 1', '"format_version": 1, "format_version": 1'
            )
        )
        self.reject()

    def test_gzip_corruption_refused_with_matching_hash(self):
        self.pair()
        artifact = self.manifest["artifacts"]["sql"]
        data = b"malformed gzip"
        artifact.update(sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
        (self.directory / artifact["name"]).write_bytes(data)
        (self.directory / (artifact["name"] + ".sha256")).write_text(
            f"{artifact['sha256']}  {artifact['name']}\n"
        )
        self.save()
        self.reject()

    def test_manifest_identity_refused(self):
        self.pair()
        shutil.copyfile(self.directory / NAME, self.directory / "avelren-20261012-090000.pair.json")
        self.reject("avelren-20261012-090000.pair.json")


class RehearsalContracts(unittest.TestCase):
    def test_native_failure_does_not_expose_raw_database_error(self):
        bash = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "docker"
            executable.write_text(
                "#!/usr/bin/env bash\n"
                'case "$*" in *"postgres-bootstrap.sh fresh") '
                "echo rejected-payload-secret >&2; exit 53 ;; esac\n"
                "exit 0\n"
            )
            executable.chmod(0o700)
            env = {
                **os.environ,
                "PATH": root.as_posix() + os.pathsep + os.environ["PATH"],
                "TMPDIR": root.as_posix(),
            }
            result = subprocess.run(
                [
                    bash,
                    (ROOT / "ops/paired-restore-rehearsal.sh").as_posix(),
                    "--directory",
                    root.as_posix(),
                    "--manifest",
                    NAME,
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertNotIn("rejected-payload-secret", result.stdout + result.stderr)
            self.assertIn("native_role_bootstrap_failed", result.stderr)
            self.assertEqual(list(root.glob("avelren-paired-restore.*")), [])

    def test_failed_start_cleans_only_generated_project_and_private_work(self):
        bash = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "docker"
            executable.write_text(
                "#!/usr/bin/env bash\n"
                'printf "%s\\n" "$*" >>"$PAIRED_TEST_CALLS"\n'
                'case "$*" in *" up -d --wait db") exit 47 ;; esac\n'
                "exit 0\n"
            )
            executable.chmod(0o700)
            sentinel = root / "unrelated"
            sentinel.write_text("must remain")
            env = {
                **os.environ,
                "PATH": root.as_posix() + os.pathsep + os.environ["PATH"],
                "TMPDIR": root.as_posix(),
                "PAIRED_TEST_CALLS": (root / "calls").as_posix(),
            }
            result = subprocess.run(
                [
                    bash,
                    (ROOT / "ops/paired-restore-rehearsal.sh").as_posix(),
                    "--directory",
                    root.as_posix(),
                    "--manifest",
                    NAME,
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 47, result.stdout + result.stderr)
            calls = (root / "calls").read_text().splitlines()
            self.assertEqual(len(calls), 3)
            self.assertIn("--network none", calls[0])
            self.assertIn(":/pair-source:ro", calls[0])
            projects = [
                re.search(r"-p (avelren-paired-restore-[0-9-]+)", c).group(1) for c in calls[1:]
            ]
            self.assertEqual(projects[0], projects[1])
            self.assertIn("down --volumes --remove-orphans", calls[-1])
            self.assertEqual(sentinel.read_text(), "must remain")
            self.assertEqual(list(root.glob("avelren-paired-restore.*")), [])

    def test_inherited_production_configuration_refused_before_docker(self):
        bash = shutil.which("bash")
        if os.name == "nt":
            bash = "C:/Program Files/Git/bin/bash.exe"
        self.assertIsNotNone(bash)
        for key, value in [
            ("AVELREN_COMPOSE_PROJECT", "avelren"),
            ("DATABASE_URL", "postgresql://production/avelren"),
            ("AVELREN_SPOOL_VOLUME", "avelren_collector_spool_v1"),
            ("AVELREN_COMPOSE_FILE", "/opt/avelren/compose.yml"),
        ]:
            env = {**os.environ, key: value}
            result = subprocess.run(
                [
                    bash,
                    str(ROOT / "ops/paired-restore-rehearsal.sh"),
                    "--directory",
                    ".",
                    "--manifest",
                    NAME,
                ],
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn("rehearsal_configuration_refused", result.stderr)


if __name__ == "__main__":
    unittest.main()
