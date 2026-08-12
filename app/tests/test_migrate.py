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


# --- fail-closed (порожній каталог) -----------------------------------------


def test_empty_migrations_dir_fails(tmp_path):
    """Порожній каталог → exit 1 (fail-closed: не можна довести стан схеми)."""
    assert migrate.run(tmp_path) == 1


# --- fail-closed (стан схеми) -----------------------------------------------


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


# --- prefix gate (B2) -------------------------------------------------------


def test_history_gap_fails_without_mutation(scratch_dsn):
    """Пропуск у записаній історії (наприклад 001+003 без 002) → FAIL до
    застосування будь-яких нових файлів."""
    assert migrate.run(MIGRATIONS) == 0
    # Видаляємо середину, щоб утворити gap.
    with psycopg.connect(scratch_dsn, autocommit=True) as c:
        c.execute("DELETE FROM schema_migrations WHERE version = '004_alerts'")
    count_before = _count_migrations(scratch_dsn)
    assert migrate.run(MIGRATIONS) == 1
    # Кількість записів не змінилась — жодної mutation не відбулось.
    assert _count_migrations(scratch_dsn) == count_before


def test_history_future_version_fails_without_mutation(scratch_dsn):
    """Запис майбутньої/чужої версії в schema_migrations → FAIL до mutation."""
    assert migrate.run(MIGRATIONS) == 0
    with psycopg.connect(scratch_dsn, autocommit=True) as c:
        c.execute(
            "INSERT INTO schema_migrations (version, sha256) VALUES ('099_future', 'x')"
        )
    count_before = _count_migrations(scratch_dsn)
    assert migrate.run(MIGRATIONS) == 1
    assert _count_migrations(scratch_dsn) == count_before


def test_broken_007_fails_before_applying_008_009(scratch_dsn, tmp_path):
    """Битий фізичний контракт 007 → FAIL до застосування 008 і 009.

    Зараз: pre-apply prefix gate перевіряє фізичну схему перед тим, як
    застосовувати pending-файли. Без цього gate-у migrator би записав 008+009
    в БД з уже некоректною схемою 007, і лише потім впав би на post-verify.
    """
    # Накатуємо тільки перші 7 міграцій.
    partial = tmp_path / "migrations"
    partial.mkdir()
    for f in sorted(MIGRATIONS.glob("*.sql"))[:7]:
        (partial / f.name).write_bytes(f.read_bytes())
    assert migrate.run(partial) == 0

    # Ламаємо контракт 007 (втрата secret_hash).
    with psycopg.connect(scratch_dsn, autocommit=True) as c:
        c.execute("ALTER TABLE devices DROP COLUMN secret_hash")

    # Запускаємо проти всіх 9 — має впасти ДО застосування 008+009.
    assert migrate.run(MIGRATIONS) == 1

    with psycopg.connect(scratch_dsn, autocommit=True) as c:
        versions = {r[0] for r in c.execute("SELECT version FROM schema_migrations").fetchall()}
    assert "008_notification_cancels" not in versions
    assert "009_observability" not in versions


def test_valid_007_applies_008_009(scratch_dsn, tmp_path):
    """Коректний контракт 007 → 008 і 009 застосовуються успішно."""
    partial = tmp_path / "migrations"
    partial.mkdir()
    for f in sorted(MIGRATIONS.glob("*.sql"))[:7]:
        (partial / f.name).write_bytes(f.read_bytes())
    assert migrate.run(partial) == 0

    # Контракт 007 цілий — запускаємо повний набір.
    assert migrate.run(MIGRATIONS) == 0

    assert _count_migrations(scratch_dsn) == len(list(MIGRATIONS.glob("*.sql")))


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


def test_verify_contract_detects_missing_subscriptions_unique(scratch_dsn):
    """Втрата UNIQUE(device_id, checkpoint_id, threshold) → verify_contract ловить.

    POST /subscriptions покладається на ON CONFLICT (device_id, checkpoint_id, threshold);
    якщо constraint загубився при restore — запит впаде з неочікуваною помилкою на проді.
    """
    assert migrate.run(MIGRATIONS) == 0
    with psycopg.connect(scratch_dsn, autocommit=True) as c:
        c.execute(
            "ALTER TABLE subscriptions "
            "DROP CONSTRAINT subscriptions_device_id_checkpoint_id_threshold_key"
        )
        problems = schema_verify.verify_contract(c)
    assert any("subscriptions_device_id_checkpoint_id_threshold_key" in p for p in problems)


def test_verify_contract_detects_nonunique_invariant_index(scratch_dsn):
    """Перетворення UNIQUE partial index на звичайний → verify_contract ловить.

    alerts_one_pending_per_subscription мусить бути UNIQUE: без цього можна
    вставити два pending-алерти на одну підписку і notifier дублюватиме сповіщення.
    """
    assert migrate.run(MIGRATIONS) == 0
    with psycopg.connect(scratch_dsn, autocommit=True) as c:
        c.execute("DROP INDEX alerts_one_pending_per_subscription")
        c.execute(
            "CREATE INDEX alerts_one_pending_per_subscription "
            "ON alerts (subscription_id) WHERE status = 'pending'"
        )
        problems = schema_verify.verify_contract(c)
    assert any(
        "alerts_one_pending_per_subscription" in p and "UNIQUE" in p
        for p in problems
    )


def test_verify_contract_detects_wrong_predicate_on_invariant_index(scratch_dsn):
    """Same-name UNIQUE partial index, але з іншим predicate → FAIL.

    Тільки uniqueness+partial недостатньо: DROP+CREATE із тим же іменем, але
    predicate `status = 'acknowledged'` замість `status = 'pending'` тримає
    зовсім інший інваріант; API продовжуватиме генерувати pending-дублікати.
    """
    assert migrate.run(MIGRATIONS) == 0
    with psycopg.connect(scratch_dsn, autocommit=True) as c:
        c.execute("DROP INDEX alerts_one_pending_per_subscription")
        c.execute(
            "CREATE UNIQUE INDEX alerts_one_pending_per_subscription "
            "ON alerts (subscription_id) WHERE status = 'acknowledged'"
        )
        problems = schema_verify.verify_contract(c)
    assert any(
        "alerts_one_pending_per_subscription" in p and "predicate" in p
        for p in problems
    ), problems


def test_verify_contract_detects_wrong_columns_on_invariant_index(scratch_dsn):
    """Same-name UNIQUE partial index на інших columns → FAIL."""
    assert migrate.run(MIGRATIONS) == 0
    with psycopg.connect(scratch_dsn, autocommit=True) as c:
        c.execute("DROP INDEX alerts_one_pending_per_subscription")
        c.execute(
            "CREATE UNIQUE INDEX alerts_one_pending_per_subscription "
            "ON alerts (checkpoint_id) WHERE status = 'pending'"
        )
        problems = schema_verify.verify_contract(c)
    assert any(
        "alerts_one_pending_per_subscription" in p and "columns" in p
        for p in problems
    ), problems


def test_verify_contract_detects_wrong_columns_on_named_constraint(scratch_dsn):
    """Same-name UNIQUE constraint на інших columns → FAIL.

    ON CONFLICT (device_id, checkpoint_id, threshold) у API покладається саме
    на ці columns; constraint з тим же іменем але (device_id) впаде на проді
    з неочікуваною помилкою "no unique constraint matching...".
    """
    assert migrate.run(MIGRATIONS) == 0
    with psycopg.connect(scratch_dsn, autocommit=True) as c:
        c.execute(
            "ALTER TABLE subscriptions "
            "DROP CONSTRAINT subscriptions_device_id_checkpoint_id_threshold_key"
        )
        # Створюємо constraint з тим самим іменем, але зовсім іншими columns.
        # Спершу треба звільнити device_id від дубль-значень (у чистій БД він порожній).
        c.execute(
            "ALTER TABLE subscriptions "
            "ADD CONSTRAINT subscriptions_device_id_checkpoint_id_threshold_key "
            "UNIQUE (device_id)"
        )
        problems = schema_verify.verify_contract(c)
    assert any(
        "subscriptions_device_id_checkpoint_id_threshold_key" in p and "columns" in p
        for p in problems
    ), problems


# --- restore smoke ----------------------------------------------------------


def test_restore_smoke_passes_on_migrated_db(scratch_dsn, monkeypatch):
    """DR-контракт: справжній застосунок піднімається проти щойно змігрованої
    БД з реальними даними і проходить prod-guard + health + auth + devices/secret
    + protected-запит."""
    from avelren import db, restore_smoke

    monkeypatch.setenv("AVELREN_RESTORE_VERIFY_TARGET", "restore_test")
    monkeypatch.setenv("AVELREN_RESTORE_VERIFY_ROLE", "avelren_api")
    monkeypatch.setattr(restore_smoke, "dsn_identity_problems", lambda *_: [])

    assert migrate.run(MIGRATIONS) == 0

    # Засіваємо мінімум даних: checkpoint + observation. Без них /health
    # повертає last_observation=null → smoke завалиться на DR gap check.
    with psycopg.connect(scratch_dsn, autocommit=True) as c:
        c.execute(
            "INSERT INTO checkpoints (id, title, for_vehicle_type) VALUES (1, 'Test', 0)"
        )
        c.execute(
            "INSERT INTO observations "
            "(time, checkpoint_id, wait_time_seconds, vehicles_in_queue, is_paused) "
            "VALUES (now(), 1, 60, 5, false)"
        )

    db._pool = None  # свіжий пул саме на scratch-БД
    try:
        assert restore_smoke.main() == 0
    finally:
        db._pool = None


def test_restore_smoke_fails_on_empty_observations(scratch_dsn, monkeypatch):
    """Правильна схема, але нульові дані → smoke повертає 1 (DR false PASS неприйнятний).

    /health на AvelRen повертає 200 навіть без observations; тому smoke явно
    перевіряє last_observation != null, щоб відрізнити «відновлено» від «схема є,
    даних немає».
    """
    from avelren import db, restore_smoke

    monkeypatch.setenv("AVELREN_RESTORE_VERIFY_TARGET", "restore_test")
    monkeypatch.setenv("AVELREN_RESTORE_VERIFY_ROLE", "avelren_api")
    monkeypatch.setattr(restore_smoke, "dsn_identity_problems", lambda *_: [])

    assert migrate.run(MIGRATIONS) == 0
    db._pool = None
    try:
        assert restore_smoke.main() == 1
    finally:
        db._pool = None


def test_restore_smoke_refuses_production_db(monkeypatch):
    """Smoke відмовляється запускатись, якщо current_database() == 'avelren'."""
    from avelren import restore_smoke

    monkeypatch.setenv("AVELREN_RESTORE_VERIFY_TARGET", "restore_test")
    monkeypatch.setenv("AVELREN_RESTORE_VERIFY_ROLE", "avelren_api")
    monkeypatch.setattr(
        restore_smoke,
        "dsn_identity_problems",
        lambda *_: ["database identity mismatch: expected restore_test, got avelren"],
    )
    assert restore_smoke.main() == 1


# --- helpers ----------------------------------------------------------------


def _migrate_schema_ddl() -> str:
    # Той самий DDL, що створює migrate для таблиці історії — щоб тест міг її
    # прочитати навіть коли міграція не дійшла до створення.
    return migrate._SCHEMA
