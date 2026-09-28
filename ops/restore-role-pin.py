#!/usr/bin/env python3
"""Validate a sanitised production-restore evidence record against one source tree."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


REQUIRED_KEYS = {
    "target_commit",
    "recovery_migration_pin",
    "database_journal",
    "role_model",
    "roles",
    "role_memberships",
    "ownership_and_grants_verified",
    "backup_sha256",
}
EXPECTED_ROLES = {
    "avelren_admin": {"login": True, "superuser": True},
    "avelren_migrator": {"login": True, "superuser": False},
    "avelren_backup": {"login": True, "superuser": False},
    "avelren_collector": {"login": True, "superuser": False},
    "avelren_notifier": {"login": True, "superuser": False},
    "avelren_watchdog": {"login": True, "superuser": False},
    "avelren_api": {"login": True, "superuser": False},
}
LOWER_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
LOWER_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
MIGRATION_STEM = re.compile(r"([0-9]{3})_[a-z0-9][a-z0-9_]*\Z")
ROLE_MODEL = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")


class EvidenceError(ValueError):
    """A category-only failure safe to show in an operator log."""


def _load_record(record_path: Path) -> dict[str, Any]:
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvidenceError("record format") from exc
    if not isinstance(record, dict) or set(record) != REQUIRED_KEYS:
        raise EvidenceError("record keys")
    return record


def _migration_files(source_root: Path) -> list[Path]:
    try:
        root = source_root.resolve(strict=True)
        migrations_dir = (root / "db" / "migrations").resolve(strict=True)
    except OSError as exc:
        raise EvidenceError("migration path") from exc
    if not migrations_dir.is_relative_to(root):
        raise EvidenceError("migration path")

    files = sorted(migrations_dir.glob("[0-9][0-9][0-9]_*.sql"), key=lambda path: path.name)
    if not files:
        raise EvidenceError("database_journal")
    for index, path in enumerate(files, start=1):
        match = MIGRATION_STEM.fullmatch(path.stem)
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise EvidenceError("migration path") from exc
        if not resolved.is_relative_to(root):
            raise EvidenceError("migration path")
        if match is None or int(match.group(1)) != index:
            raise EvidenceError("database_journal")
    return files


def validate_evidence(record_path: Path, source_root: Path, dump_sha256: str) -> dict[str, object]:
    record = _load_record(Path(record_path))

    if not isinstance(record["target_commit"], str) or not LOWER_COMMIT.fullmatch(record["target_commit"]):
        raise EvidenceError("target_commit")
    pin = record["recovery_migration_pin"]
    if not isinstance(pin, str) or pin == "latest" or MIGRATION_STEM.fullmatch(pin) is None:
        raise EvidenceError("recovery_migration_pin")
    if not isinstance(record["role_model"], str) or ROLE_MODEL.fullmatch(record["role_model"]) is None:
        raise EvidenceError("role_model")
    if not isinstance(dump_sha256, str) or LOWER_SHA256.fullmatch(dump_sha256) is None:
        raise EvidenceError("backup_sha256")
    if record["backup_sha256"] != dump_sha256:
        raise EvidenceError("backup_sha256")

    files = _migration_files(Path(source_root))
    stems = [path.stem for path in files]
    if pin not in stems:
        raise EvidenceError("recovery_migration_pin")
    pinned_files = files[: stems.index(pin) + 1]
    journal = record["database_journal"]
    if not isinstance(journal, dict) or list(journal) != [path.stem for path in pinned_files]:
        raise EvidenceError("database_journal")
    for path in pinned_files:
        digest = journal.get(path.stem)
        if not isinstance(digest, str) or LOWER_SHA256.fullmatch(digest) is None:
            raise EvidenceError("database_journal")
        try:
            actual_digest = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            raise EvidenceError("migration path") from exc
        if actual_digest != digest:
            raise EvidenceError("database_journal")

    roles = record["roles"]
    if (not isinstance(roles, dict) or set(roles) != set(EXPECTED_ROLES)
            or any(not isinstance(value, dict) or set(value) != {"login", "superuser"}
                   or type(value["login"]) is not bool or type(value["superuser"]) is not bool
                   or value != EXPECTED_ROLES[name]
                   for name, value in roles.items())):
        raise EvidenceError("roles")
    memberships = record["role_memberships"]
    if (not isinstance(memberships, dict)
            or set(memberships) != set(EXPECTED_ROLES)
            or any(value != [] for value in memberships.values())):
        raise EvidenceError("role_memberships")
    if record["ownership_and_grants_verified"] is not True:
        raise EvidenceError("ownership_and_grants_verified")

    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--record", type=Path, required=True)
    verify.add_argument("--source-root", type=Path, required=True)
    verify.add_argument("--dump-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        validate_evidence(args.record, args.source_root, args.dump_sha256)
    except EvidenceError as exc:
        print(f"production restore evidence rejected: {exc}", file=sys.stderr)
        return 1
    print("production restore evidence verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
