#!/usr/bin/env python3
"""Static contract tests for the source-only deployment preflight gate."""

from __future__ import annotations

import importlib.util
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = ROOT / "ops" / "deployment-preflight.py"
SPEC = importlib.util.spec_from_file_location("deployment_preflight", MODULE_PATH)
assert SPEC and SPEC.loader
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)

source_text = MODULE_PATH.read_text(encoding="utf-8").lower()
for forbidden_capability in (
    "import subprocess",
    "import socket",
    "import paramiko",
    "subprocess.",
    "os.system(",
):
    assert forbidden_capability not in source_text, forbidden_capability

COMMIT = "a" * 40
DIGEST = "sha256:" + "b" * 64


def valid_evidence() -> dict:
    migrations = preflight.source_migrations()
    return {
        "format_version": 1,
        "captured_at": "2026-09-25T00:00:00Z",
        "target_commit": COMMIT,
        "server_checkout": {
            "clean": True,
            "commit": COMMIT,
            "migration_files": migrations,
        },
        "database_journal": migrations,
        "runtime_images": {
            service: {"source_commit": COMMIT, "image_digest": DIGEST}
            for service in sorted(preflight.RUNTIME_SERVICES)
        },
        "checks": {
            "backup_verified": True,
            "health_verified": True,
            "schema_verified": True,
        },
    }


def expect_failure(evidence: dict, phrase: str) -> None:
    errors = preflight.evaluate(evidence, COMMIT)
    assert any(phrase in error for error in errors), errors


valid_errors = preflight.evaluate(valid_evidence(), COMMIT)
assert valid_errors == [], valid_errors

dirty = valid_evidence()
dirty["server_checkout"]["clean"] = False
expect_failure(dirty, "server_checkout.clean")

missing_file = valid_evidence()
missing_file["server_checkout"]["migration_files"].pop("013_admin_installation_lock")
expect_failure(missing_file, "checkout migration files")

wrong_journal = valid_evidence()
wrong_journal["database_journal"]["011_admin_access"] = "0" * 64
expect_failure(wrong_journal, "database journal")

wrong_image = valid_evidence()
wrong_image["runtime_images"]["watchdog"]["source_commit"] = "c" * 40
expect_failure(wrong_image, "runtime image watchdog")

missing_health = valid_evidence()
missing_health["checks"]["health_verified"] = False
expect_failure(missing_health, "checks must prove")

secret = valid_evidence()
secret["database_dsn"] = "must never be accepted"
expect_failure(secret, "forbidden")

wrong_target = deepcopy(valid_evidence())
wrong_target["target_commit"] = "d" * 40
expect_failure(wrong_target, "target_commit")

print("deployment preflight contract: PASS")
