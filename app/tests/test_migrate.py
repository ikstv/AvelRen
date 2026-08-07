"""Fail-closed міграції і звірка схеми з історією (A-07).

Кожен сценарій — на власній одноразовій БД: migrate.run() працює через
settings.database_url, тож фікстура створює порожню базу, перенаправляє
налаштування на неї й прибирає після тесту.
"""

import os
import random
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from avelren import migrate, schema_verify
from avelren.config import settings

DSN = os.environ["DATABASE_URL"]
MIGRATIONS = Path("db/migrations")


def _swap_dbname(dsn: str, dbname: str) -> str:
    parts = conninfo_to_dict(dsn)
    parts["dbname"] = dbname
    return make_conninfo(**parts)


@pytest.fixture()
def scratch_dsn(monkeypatch):
    """Порожня одноразова БД + settings.database_url, спрямований на неї."""
    name = f"avelren_ci_mig{random.randrange(10**9)}"
    admin = psycopg.connect(DSN, autocommit=True)
    admin.execute(f'CREATE DATABASE "{name}"')
    dsn = _swap_dbname(DSN, name)
    monkeypatch.setattr(settings, "database_url", dsn)
    try:
        yield dsn
    finally:
        try:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        finally:
            admin.close()


def _count_migrations(dsn: str) -> int:
    with psycopg.connect(dsn, autocommit=True) as c:
        return c.execute("SELECT count(*) FROM schema_migrations").fetchone()[0]


# --- нормальні шляхи --------------------------------------------------------


def test_clean_db_applies_all(scratch_dsn):
    assert migrate.run(MIGRATIONS) == 0
    assert _count_migrations(scratch_dsn) == len(list(MIGRATIONS.glob("*.sql")))


def test_current_db_applies_nothing(scratch_dsn):
    assert migrate.run(MIGRATIONS) == 0
    # Повторний запуск — ідемпотентний, нічого не застосовує, все ще 0 exit.
    assert migrate.run(MIGRATIONS) == 0


# --- fail-closed ------------------------------------------------------------


def test_existing_schema_without_history_fails_closed(scratch_dsn):
    """Будь-який AvelRen-обʼєкт при порожній історії → FAIL, не mark-all."""
    with psycopg.connect(scratch_dsn, autocommit=True) as c:
        c.execute("CREATE TABLE checkpoints (id integer PRIMARY KEY)")
    assert migrate.run(MIGRATIONS) == 1
    # Нічого не записано в історію — саме це головне.
    with psycopg.connect(scratch_dsn, autocommit=True) as c:
        c.execute(_migrate_schema_ddl())
        assert c.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 0


def test_partial_schema_without_checkpoints_also_fails(scratch_dsn):
    """Навіть коли саме checkpoints нема, інший відомий обʼєкт → теж FAIL
    (стара евристика дивилась лише на checkpoints)."""
    with psycopg.connect(scratch_dsn, autocommit=True) as c:
        c.execute("CREATE TABLE devices (id uuid PRIMARY KEY)")
    assert migrate.run(MIGRATIONS) == 1


def test_changed_migration_sha_fails(scratch_dsn):
    assert migrate.run(MIGRATIONS) == 0
    with psycopg.connect(scratch_dsn, autocommit=True) as c:
        c.execute("UPDATE schema_migrations SET sha256 = 'deadbeef' WHERE version = '004_alerts'")
    assert migrate.run(MIGRATIONS) == 1


def test_history_ok_but_missing_column_fails(scratch_dsn):
    """Головний партковий-restore сценарій: історія повна й SHA правильні, але
    фізично колонки нема — post-apply schema_verify мусить це зловити."""
    assert migrate.run(MIGRATIONS) == 0
    with psycopg.connect(scratch_dsn, autocommit=True) as c:
        c.execute("ALTER TABLE devices DROP COLUMN secret_hash")
    # Наступний запуск застосовувати нема чого, але verify має впасти.
    assert migrate.run(MIGRATIONS) == 1


# --- schema_verify напряму --------------------------------------------------


def test_schema_verify_passes_on_full_db(scratch_dsn):
    assert migrate.run(MIGRATIONS) == 0
    with psycopg.connect(scratch_dsn, autocommit=True) as c:
        assert schema_verify.verify(c, MIGRATIONS) == []


def test_verify_history_detects_missing_and_future(scratch_dsn):
    assert migrate.run(MIGRATIONS) == 0
    with psycopg.connect(scratch_dsn, autocommit=True) as c:
        c.execute("DELETE FROM schema_migrations WHERE version = '009_observability'")
        c.execute(
            "INSERT INTO schema_migrations (version, sha256) VALUES ('099_future', 'x')"
        )
        problems = schema_verify.verify_history(c, MIGRATIONS)
    joined = " ".join(problems)
    assert "009_observability" in joined  # пропущена
    assert "099_future" in joined         # чужа/майбутня


def test_verify_contract_detects_dropped_index(scratch_dsn):
    assert migrate.run(MIGRATIONS) == 0
    with psycopg.connect(scratch_dsn, autocommit=True) as c:
        c.execute("DROP INDEX alerts_one_pending_per_subscription")
        problems = schema_verify.verify_contract(c)
    assert any("alerts_one_pending_per_subscription" in p for p in problems)


def test_restore_smoke_passes_on_migrated_db(scratch_dsn):
    """DR-контракт: справжній застосунок піднімається проти щойно змігрованої
    БД і проходить health + auth + devices/secret + protected-запит."""
    from avelren import db, restore_smoke

    assert migrate.run(MIGRATIONS) == 0
    db._pool = None  # свіжий пул саме на scratch-БД
    try:
        assert restore_smoke.main() == 0
    finally:
        db._pool = None


def _migrate_schema_ddl() -> str:
    # Той самий DDL, що створює migrate для таблиці історії — щоб тест міг її
    # прочитати навіть коли міграція не дійшла до створення.
    return migrate._SCHEMA
