#!/usr/bin/env python3
"""Контракт: allowlist відношень у restore-рушії не має розходитися зі схемою.

Спосіб зламатися (аудит H-1): `deploy/restore-engine.lib.sh` двічі хардкодить
перелік із 20 прикладних відношень (14 таблиць/в'юх + 6 послідовностей). Якщо
майбутня міграція додасть таблицю, а цей перелік не оновити, production-restore
впаде з `restore application relation allowlist mismatch` — але вже ПІСЛЯ
`dropdb`, тобто посеред disaster recovery, лишивши систему без бази.

Ця перевірка перетворює «тиху міну до наступної аварії» на «червоний CI на PR»:
вона звіряє allowlist рушія з єдиним enforced-джерелом правди
(`schema_verify._TABLES_V`, який перевіряє `migrate.py` після кожної міграції) і
з `bigserial`-послідовностями, оголошеними в `db/migrations/*.sql`. БД не потрібна
— перевірка суто статична.

Запускати з CI: `python3 deploy/restore-allowlist-contract-test.py`.
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
    """Повертає по одному набору (relation_name, relation_kind) на кожен
    хардкоджений блок allowlist у рушії. Блоків має бути ≥2 і всі однакові."""
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
            # Перший рядок без кортежу (напр. `),` чи `actual AS (`) — кінець блоку.
            break
        if current:
            blocks.append(current)
    return blocks


def _parse_schema_verify_tables(text: str) -> set[str]:
    """Імена таблиць/в'юх із `_TABLES_V` (другий елемент кожного кортежу)."""
    block = re.search(r"_TABLES_V\b.*?=\s*\[(.*?)\n\]", text, re.DOTALL)
    if not block:
        raise SystemExit("НЕ ЗНАЙДЕНО _TABLES_V у schema_verify.py — змінили формат?")
    return set(re.findall(r"\(\s*(?:None|\"[^\"]*\")\s*,\s*\"([^\"]+)\"", block.group(1)))


def _derive_sequences_from_migrations() -> set[str]:
    """Послідовності, які створює `bigserial`/`serial`, названі `<таблиця>_<колонка>_seq`."""
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
            print(f"НЕ ЗНАЙДЕНО обов'язковий шлях: {required}", file=sys.stderr)
            return 2

    engine_text = RESTORE_ENGINE.read_text(encoding="utf-8")
    blocks = _parse_engine_allowlist(engine_text)
    if len(blocks) < 2:
        print(
            "Очікували ≥2 хардкоджені блоки allowlist у restore-engine.lib.sh, "
            f"знайшли {len(blocks)}. Формат змінився — онови цю перевірку.",
            file=sys.stderr,
        )
        return 1

    # Обидва блоки мусять бути ідентичні: інакше хтось оновив один, забув інший.
    if any(b != blocks[0] for b in blocks[1:]):
        print(
            "Хардкоджені блоки allowlist у restore-engine.lib.sh РОЗІЙШЛИСЯ між "
            "собою — оновлено один, а не всі. Зроби їх однаковими.",
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
            "У schema_verify._TABLES_V є, а в allowlist рушія НЕМАЄ таблиць: "
            + ", ".join(sorted(missing_tables))
        )
    if extra_tables:
        errors.append(
            "В allowlist рушія є зайві таблиці, яких немає в schema_verify._TABLES_V: "
            + ", ".join(sorted(extra_tables))
        )

    missing_seqs = derived_seqs - engine_seqs
    extra_seqs = engine_seqs - derived_seqs
    if missing_seqs:
        errors.append(
            "Міграції створюють послідовності, яких НЕМАЄ в allowlist рушія: "
            + ", ".join(sorted(missing_seqs))
        )
    if extra_seqs:
        errors.append(
            "В allowlist рушія є послідовності, яких не створює жодна міграція: "
            + ", ".join(sorted(extra_seqs))
        )

    if errors:
        print("КОНТРАКТ RESTORE ALLOWLIST ПОРУШЕНО:\n", file=sys.stderr)
        for e in errors:
            print(f"  • {e}", file=sys.stderr)
        print(
            "\nОнови обидва блоки `expected(...)` у deploy/restore-engine.lib.sh, "
            "щоб вони збігалися зі схемою. Інакше production-restore впаде вже "
            "ПІСЛЯ dropdb, посеред аварії (аудит H-1).",
            file=sys.stderr,
        )
        return 1

    print(
        f"OK: allowlist рушія збігається зі схемою "
        f"({len(engine_tables)} таблиць/в'юх, {len(engine_seqs)} послідовностей)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
