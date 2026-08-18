#!/usr/bin/env python3
"""Contract: the relation allowlist in the restore engine must not diverge from the schema.

How it can break (audit H-1): `deploy/restore-engine.lib.sh` hardcodes the list
of 20 application relations twice (14 tables/views + 6 sequences). If a future
migration adds a table and this list is not updated, the production restore fails
with `restore application relation allowlist mismatch` — but already AFTER
`dropdb`, i.e. in the middle of disaster recovery, leaving the system without a
database.

This check turns "a silent mine until the next incident" into "red CI on a PR":
it compares the engine's allowlist against the single enforced source of truth
(`schema_verify._TABLES_V`, which `migrate.py` verifies after every migration)
and against the `bigserial` sequences declared in `db/migrations/*.sql`. No DB is
needed — the check is purely static.

Run from CI: `python3 deploy/restore-allowlist-contract-test.py`.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RESTORE_ENGINE = REPO_ROOT / "deploy" / "restore-engine.lib.sh"
SCHEMA_VERIFY = REPO_ROOT / "app" / "src" / "avelren" / "schema_verify.py"
MIGRATIONS_DIR = REPO_ROOT / "db" / "migrations"

_TUPLE_RE = re.compile(r"\(\s*'public'\s*,\s*'([^']+)'\s*,\s*'([^']+)'\s*\)")
_BLOCK_HEADER = "expected(schema_name, relation_name, relation_kind) AS ("


def _parse_engine_allowlist(text: str) -> list[set[tuple[str, str]]]:
    """Returns one set of (relation_name, relation_kind) per hardcoded allowlist
    block in the engine. There must be ≥2 blocks and all identical."""
    blocks: list[set[tuple[str, str]]] = []
    for start in (m.end() for m in re.finditer(re.escape(_BLOCK_HEADER), text)):
        current: set[tuple[str, str]] = set()
        for line in text[start:].splitlines():
            stripped = line.strip()
            if not stripped or stripped.upper().startswith("VALUES"):
                continue
            found = _TUPLE_RE.findall(line)
            if found:
                for name, kind in found:
                    current.add((name, kind))
                continue
            # The first line without a tuple (e.g. `),` or `actual AS (`) — end of block.
            break
        if current:
            blocks.append(current)
    return blocks


def _parse_schema_verify_tables(text: str) -> set[str]:
    """Table/view names from `_TABLES_V` (the second element of each tuple)."""
    block = re.search(r"_TABLES_V\b.*?=\s*\[(.*?)\n\]", text, re.DOTALL)
    if not block:
        raise SystemExit("_TABLES_V not found in schema_verify.py — did the format change?")
    return set(re.findall(r"\(\s*(?:None|\"[^\"]*\")\s*,\s*\"([^\"]+)\"", block.group(1)))


def _derive_sequences_from_migrations() -> set[str]:
    """Sequences created by `bigserial`/`serial`, named `<table>_<column>_seq`."""
    seqs: set[str] = set()
    create_re = re.compile(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:public\.)?(\w+)\s*\((.*?)\)\s*;",
        re.IGNORECASE | re.DOTALL,
    )
    col_re = re.compile(r"(\w+)\s+(?:big)?serial\b", re.IGNORECASE)
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        for table, body in create_re.findall(sql):
            for col in col_re.findall(body):
                seqs.add(f"{table}_{col}_seq")
    return seqs


def main() -> int:
    for required in (RESTORE_ENGINE, SCHEMA_VERIFY, MIGRATIONS_DIR):
        if not required.exists():
            print(f"Required path not found: {required}", file=sys.stderr)
            return 2

    engine_text = RESTORE_ENGINE.read_text(encoding="utf-8")
    blocks = _parse_engine_allowlist(engine_text)
    if len(blocks) < 2:
        print(
            "Expected ≥2 hardcoded allowlist blocks in restore-engine.lib.sh, "
            f"found {len(blocks)}. The format changed — update this check.",
            file=sys.stderr,
        )
        return 1

    # Both blocks must be identical: otherwise someone updated one and forgot the other.
    if any(b != blocks[0] for b in blocks[1:]):
        print(
            "The hardcoded allowlist blocks in restore-engine.lib.sh have DIVERGED "
            "from each other — one was updated, not all. Make them identical.",
            file=sys.stderr,
        )
        return 1

    engine = blocks[0]
    engine_tables = {name for name, kind in engine if kind != "S"}
    engine_seqs = {name for name, kind in engine if kind == "S"}

    schema_tables = _parse_schema_verify_tables(SCHEMA_VERIFY.read_text(encoding="utf-8"))
    derived_seqs = _derive_sequences_from_migrations()

    errors: list[str] = []

    missing_tables = schema_tables - engine_tables
    extra_tables = engine_tables - schema_tables
    if missing_tables:
        errors.append(
            "Present in schema_verify._TABLES_V but MISSING from the engine allowlist: "
            + ", ".join(sorted(missing_tables))
        )
    if extra_tables:
        errors.append(
            "Extra tables in the engine allowlist that are not in schema_verify._TABLES_V: "
            + ", ".join(sorted(extra_tables))
        )

    missing_seqs = derived_seqs - engine_seqs
    extra_seqs = engine_seqs - derived_seqs
    if missing_seqs:
        errors.append(
            "Migrations create sequences MISSING from the engine allowlist: "
            + ", ".join(sorted(missing_seqs))
        )
    if extra_seqs:
        errors.append(
            "The engine allowlist has sequences that no migration creates: "
            + ", ".join(sorted(extra_seqs))
        )

    if errors:
        print("RESTORE ALLOWLIST CONTRACT VIOLATED:\n", file=sys.stderr)
        for e in errors:
            print(f"  • {e}", file=sys.stderr)
        print(
            "\nUpdate both `expected(...)` blocks in deploy/restore-engine.lib.sh "
            "so they match the schema. Otherwise the production restore will fail "
            "AFTER dropdb, in the middle of an incident (audit H-1).",
            file=sys.stderr,
        )
        return 1

    print(
        f"OK: the engine allowlist matches the schema "
        f"({len(engine_tables)} tables/views, {len(engine_seqs)} sequences)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
