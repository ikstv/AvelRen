#!/usr/bin/env python3
"""Fail-closed, source-only gate for a future production deployment.

This program intentionally does not open SSH connections, invoke Docker or read
an env file.  An operator first captures a sanitised, read-only evidence JSON;
the gate compares that evidence with the checked-out source.  Passing this gate
is evidence for review, never authorisation to deploy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = ROOT / "db" / "migrations"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^[0-9a-f]{40}$")
RUNTIME_SERVICES = frozenset({"api", "collector", "notifier", "watchdog"})
FORBIDDEN_EVIDENCE_KEYS = frozenset({"dsn", "password", "token", "private_key", "secret_value"})


def source_migrations(directory: Path = MIGRATIONS) -> dict[str, str]:
    """Return migration stem -> exact UTF-8 file SHA-256."""
    result: dict[str, str] = {}
    for path in sorted(directory.glob("*.sql")):
        result[path.stem] = hashlib.sha256(path.read_bytes()).hexdigest()
    if not result:
        raise ValueError(f"no source migrations found in {directory}")
    return result


def _mapping(value: Any, label: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        errors.append(f"{label} must be an object")
        return {}
    return value


def _contains_forbidden_key(value: Any, path: str = "$") -> str | None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if not isinstance(key, str):
                return f"{path} has a non-string key"
            normalized = key.lower().replace("-", "_")
            credential_suffix = normalized.endswith(
                ("_dsn", "_password", "_token", "_private_key")
            )
            if normalized in FORBIDDEN_EVIDENCE_KEYS or credential_suffix:
                return f"{path}.{key} is forbidden; evidence must not contain secrets"
            found = _contains_forbidden_key(nested, f"{path}.{key}")
            if found:
                return found
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found = _contains_forbidden_key(nested, f"{path}[{index}]")
            if found:
                return found
    return None


def evaluate(evidence: Any, source_commit: str, migrations_dir: Path = MIGRATIONS) -> list[str]:
    """Return every blocking problem; an empty list means the evidence is coherent."""
    errors: list[str] = []
    if not COMMIT.fullmatch(source_commit):
        return ["source commit must be a lowercase 40-character Git SHA"]

    secret_problem = _contains_forbidden_key(evidence)
    if secret_problem:
        return [secret_problem]

    root = _mapping(evidence, "evidence", errors)
    if root.get("format_version") != 1:
        errors.append("format_version must be exactly 1")
    if not isinstance(root.get("captured_at"), str) or not root["captured_at"].endswith("Z"):
        errors.append("captured_at must be a UTC timestamp ending in Z")

    target = root.get("target_commit")
    if target != source_commit:
        errors.append("target_commit does not equal the reviewed source commit")

    checkout = _mapping(root.get("server_checkout"), "server_checkout", errors)
    if checkout.get("clean") is not True:
        errors.append("server_checkout.clean must be true")
    if checkout.get("commit") != source_commit:
        errors.append("server_checkout.commit does not equal target_commit")

    expected_migrations = source_migrations(migrations_dir)
    checkout_migrations = checkout.get("migration_files")
    if not isinstance(checkout_migrations, dict):
        errors.append("server_checkout.migration_files must be an object")
    elif checkout_migrations != expected_migrations:
        errors.append("server checkout migration files do not exactly match source migrations")

    journal = _mapping(root.get("database_journal"), "database_journal", errors)
    if journal != expected_migrations:
        errors.append("database journal does not exactly match source migration SHA-256 values")
    else:
        for version, digest in journal.items():
            if not isinstance(version, str) or not isinstance(digest, str) or not SHA256.fullmatch(digest):
                errors.append("database_journal contains an invalid migration SHA-256")
                break

    images = _mapping(root.get("runtime_images"), "runtime_images", errors)
    if set(images) != RUNTIME_SERVICES:
        errors.append("runtime_images must contain exactly api, collector, notifier and watchdog")
    for service in RUNTIME_SERVICES:
        image = images.get(service)
        if not isinstance(image, dict):
            continue
        if image.get("source_commit") != source_commit:
            errors.append(f"runtime image {service} was not built from target_commit")
        digest = image.get("image_digest")
        if not isinstance(digest, str) or not digest.startswith("sha256:") or not SHA256.fullmatch(digest[7:]):
            errors.append(f"runtime image {service} lacks a valid immutable image_digest")

    checks = _mapping(root.get("checks"), "checks", errors)
    if checks != {"backup_verified": True, "health_verified": True, "schema_verified": True}:
        errors.append("checks must prove backup_verified, health_verified and schema_verified")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True, help="sanitised read-only JSON evidence")
    parser.add_argument("--source-commit", required=True, help="reviewed 40-character Git SHA")
    args = parser.parse_args(argv)

    try:
        evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"deployment preflight: cannot read evidence: {exc}", file=sys.stderr)
        return 2

    errors = evaluate(evidence, args.source_commit)
    if errors:
        print("DEPLOYMENT PREFLIGHT: FAIL", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("DEPLOYMENT PREFLIGHT: PASS (review evidence only; deployment still requires explicit GO)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
