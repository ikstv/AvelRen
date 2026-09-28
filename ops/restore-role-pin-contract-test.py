#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "ops" / "restore-role-pin.py"
EXPECTED_ROLES = {
    "avelren_admin": {"login": True, "superuser": True},
    "avelren_migrator": {"login": True, "superuser": False},
    "avelren_backup": {"login": True, "superuser": False},
    "avelren_collector": {"login": True, "superuser": False},
    "avelren_notifier": {"login": True, "superuser": False},
    "avelren_watchdog": {"login": True, "superuser": False},
    "avelren_api": {"login": True, "superuser": False},
}


def load_module():
    spec = importlib.util.spec_from_file_location("restore_role_pin", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load restore role pin module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class RestoreRolePinContract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "source"
        migrations = self.root / "db" / "migrations"
        migrations.mkdir(parents=True)
        self.files = []
        for name, body in (
            ("001_init.sql", "select 1;\n"),
            ("002_more.sql", "select 2;\n"),
            ("003_last.sql", "select 3;\n"),
        ):
            path = migrations / name
            path.write_text(body, encoding="utf-8")
            self.files.append(path)
        self.dump_sha = "d" * 64
        self.record = {
            "target_commit": "a" * 40,
            "recovery_migration_pin": "003_last",
            "database_journal": {
                path.stem: hashlib.sha256(path.read_bytes()).hexdigest() for path in self.files
            },
            "role_model": "least-privilege-v1",
            "roles": deepcopy(EXPECTED_ROLES),
            "role_memberships": {role: [] for role in EXPECTED_ROLES},
            "ownership_and_grants_verified": True,
            "backup_sha256": self.dump_sha,
        }
        self.record_path = Path(self.tmp.name) / "evidence.json"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, record=None):
        self.record_path.write_text(json.dumps(record or self.record), encoding="utf-8")

    def rejected(self, field, record=None):
        self.write(record)
        module = load_module()
        with self.assertRaises(module.EvidenceError) as raised:
            module.validate_evidence(self.record_path, self.root, self.dump_sha)
        message = str(raised.exception)
        self.assertIn(field, message)
        self.assertNotIn("SECRET-SENTINEL", message)

    def test_valid_record_and_cli(self):
        self.write()
        module = load_module()
        self.assertEqual(module.validate_evidence(self.record_path, self.root, self.dump_sha), self.record)
        completed = subprocess.run(
            [sys.executable, str(MODULE_PATH), "verify", "--record", str(self.record_path),
             "--source-root", str(self.root), "--dump-sha256", self.dump_sha],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout, "production restore evidence verified\n")
        self.assertEqual(completed.stderr, "")

    def test_top_level_keys_are_exact(self):
        for mutation in ("missing", "extra"):
            with self.subTest(mutation=mutation):
                record = deepcopy(self.record)
                if mutation == "missing":
                    del record["role_model"]
                else:
                    record["SECRET-SENTINEL"] = "SECRET-SENTINEL"
                self.rejected("record keys", record)

    def test_commit_is_exact_lowercase_sha(self):
        for value in ("A" * 40, "a" * 39, "SECRET-SENTINEL"):
            with self.subTest(value=value):
                record = deepcopy(self.record)
                record["target_commit"] = value
                self.rejected("target_commit", record)

    def test_pin_must_be_explicit_and_present(self):
        for value in ("latest", "004_unknown", "SECRET-SENTINEL"):
            with self.subTest(value=value):
                record = deepcopy(self.record)
                record["recovery_migration_pin"] = value
                self.rejected("recovery_migration_pin", record)

    def test_journal_is_exact_ordered_contiguous_prefix(self):
        variants = []
        missing = deepcopy(self.record)
        del missing["database_journal"]["002_more"]
        variants.append(missing)
        extra = deepcopy(self.record)
        extra["database_journal"]["004_extra"] = "e" * 64
        variants.append(extra)
        reordered = deepcopy(self.record)
        reordered["database_journal"] = dict(reversed(list(reordered["database_journal"].items())))
        variants.append(reordered)
        for record in variants:
            with self.subTest(keys=list(record["database_journal"])):
                self.rejected("database_journal", record)

    def test_migration_digest_must_match_source(self):
        record = deepcopy(self.record)
        record["database_journal"]["002_more"] = "0" * 64
        self.rejected("database_journal", record)

    def test_backup_digest_must_match_argument(self):
        record = deepcopy(self.record)
        record["backup_sha256"] = "0" * 64
        self.rejected("backup_sha256", record)

    def test_roles_are_exact_and_runtime_is_not_superuser(self):
        missing = deepcopy(self.record)
        del missing["roles"]["avelren_api"]
        self.rejected("roles", missing)
        extra = deepcopy(self.record)
        extra["roles"]["SECRET-SENTINEL"] = {"login": True, "superuser": False}
        self.rejected("roles", extra)
        elevated = deepcopy(self.record)
        elevated["roles"]["avelren_api"]["superuser"] = True
        self.rejected("roles", elevated)
        numeric_boolean = deepcopy(self.record)
        numeric_boolean["roles"]["avelren_api"]["login"] = 1
        self.rejected("roles", numeric_boolean)

    def test_direct_memberships_must_be_empty_and_exact(self):
        record = deepcopy(self.record)
        record["role_memberships"]["avelren_api"] = ["avelren_admin", "SECRET-SENTINEL"]
        self.rejected("role_memberships", record)

    def test_ownership_and_grants_must_be_verified(self):
        record = deepcopy(self.record)
        record["ownership_and_grants_verified"] = False
        self.rejected("ownership_and_grants_verified", record)

    def test_role_model_is_safe_explicit_identifier(self):
        record = deepcopy(self.record)
        record["role_model"] = "SECRET-SENTINEL with spaces"
        self.rejected("role_model", record)

    def test_symlinked_migration_cannot_escape_source_root(self):
        outside = Path(self.tmp.name) / "outside.sql"
        outside.write_text("select 'outside';\n", encoding="utf-8")
        self.files[1].unlink()
        self.files[1].symlink_to(outside)
        record = deepcopy(self.record)
        record["database_journal"]["002_more"] = hashlib.sha256(outside.read_bytes()).hexdigest()
        self.rejected("migration path", record)


if __name__ == "__main__":
    unittest.main(verbosity=2)
