"""Fail-closed migrations and schema-vs-history verification (A-07).

Each scenario is on its own disposable DB: migrate.run() works through
settings.database_url, so the fixture creates an empty database, redirects the
settings to it, and cleans up after the test.
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
    """An empty disposable DB + settings.database_url pointed at it."""
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


# --- normal paths -----------------------------------------------------------


def test_clean_db_applies_all(scratch_dsn):
    assert migrate.run(MIGRATIONS) == 0
    assert _count_migrations(scratch_dsn) == len(list(MIGRATIONS.glob("*.sql")))


def test_current_db_applies_nothing(scratch_dsn):
    assert migrate.run(MIGRATIONS) == 0
    # A repeated run is idempotent, applies nothing, still exits 0.
    assert migrate.run(MIGRATIONS) == 0


# --- fail-closed (empty directory) ------------------------------------------


def test_empty_migrations_dir_fails(tmp_path):
    """Empty directory → exit 1 (fail-closed: the schema state cannot be proven)."""
    assert migrate.run(tmp_path) == 1


# --- fail-closed (schema state) ---------------------------------------------


def test_existing_schema_without_history_fails_closed(scratch_dsn):
    """Any AvelRen object with an empty history → FAIL, not mark-all."""
    with psycopg.connect(scratch_dsn, autocommit=True) as c:
        c.execute("CREATE TABLE checkpoints (id integer PRIMARY KEY)")
    assert migrate.run(MIGRATIONS) == 1
    # Nothing was written to the history — that is the main point.
    with psycopg.connect(scratch_dsn, autocommit=True) as c:
        c.execute(_migrate_schema_ddl())
        assert c.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 0


def test_partial_schema_without_checkpoints_also_fails(scratch_dsn):
    """Even when checkpoints specifically is missing, another known object → also
    FAIL (the old heuristic looked only at checkpoints)."""
    with psycopg.connect(scratch_dsn, autocommit=True) as c:
        c.execute("CREATE TABLE devices (id uuid PRIMARY KEY)")
    assert migrate.run(MIGRATIONS) == 1


def test_changed_migration_sha_fails(scratch_dsn):
    assert migrate.run(MIGRATIONS) == 0
    with psycopg.connect(scratch_dsn, autocommit=True) as c:
        c.execute("UPDATE schema_migrations SET sha256 = 'deadbeef' WHERE version = '004_alerts'")
    assert migrate.run(MIGRATIONS) == 1


def test_history_ok_but_missing_column_fails(scratch_dsn):
    """The main partial-restore scenario: history is complete and SHAs are
    correct, but the column is physically missing — post-apply schema_verify must
    catch this."""
    assert migrate.run(MIGRATIONS) == 0
    with psycopg.connect(scratch_dsn, autocommit=True) as c:
        c.execute("ALTER TABLE devices DROP COLUMN secret_hash")
    # The next run has nothing to apply, but verify must fail.
    assert migrate.run(MIGRATIONS) == 1


# --- prefix gate (B2) -------------------------------------------------------


def test_history_gap_fails_without_mutation(scratch_dsn):
    """A gap in the recorded history (e.g. 001+003 without 002) → FAIL before
    applying any new files."""
    assert migrate.run(MIGRATIONS) == 0
    # We delete the middle to create a gap.
    with psycopg.connect(scratch_dsn, autocommit=True) as c:
        c.execute("DELETE FROM schema_migrations WHERE version = '004_alerts'")
    count_before = _count_migrations(scratch_dsn)
    assert migrate.run(MIGRATIONS) == 1
    # The record count did not change — no mutation happened.
    assert _count_migrations(scratch_dsn) == count_before


def test_history_future_version_fails_without_mutation(scratch_dsn):
    """A future/foreign version recorded in schema_migrations → FAIL before mutation."""
    assert migrate.run(MIGRATIONS) == 0
    with psycopg.connect(scratch_dsn, autocommit=True) as c:
        c.execute(
            "INSERT INTO schema_migrations (version, sha256) VALUES ('099_future', 'x')"
        )
    count_before = _count_migrations(scratch_dsn)
    assert migrate.run(MIGRATIONS) == 1
    assert _count_migrations(scratch_dsn) == count_before


def test_broken_007_fails_before_applying_008_009(scratch_dsn, tmp_path):
    """A broken physical contract of 007 → FAIL before applying 008 and 009.

    Now: the pre-apply prefix gate checks the physical schema before applying
    pending files. Without this gate the migrator would record 008+009 in a DB
    with an already-incorrect 007 schema, and only then fail on post-verify.
    """
    # We apply only the first 7 migrations.
    partial = tmp_path / "migrations"
    partial.mkdir()
    for f in sorted(MIGRATIONS.glob("*.sql"))[:7]:
        (partial / f.name).write_bytes(f.read_bytes())
    assert migrate.run(partial) == 0

    # We break the 007 contract (loss of secret_hash).
    with psycopg.connect(scratch_dsn, autocommit=True) as c:
        c.execute("ALTER TABLE devices DROP COLUMN secret_hash")

    # We run against all 9 — it must fail BEFORE applying 008+009.
    assert migrate.run(MIGRATIONS) == 1

    with psycopg.connect(scratch_dsn, autocommit=True) as c:
        versions = {r[0] for r in c.execute("SELECT version FROM schema_migrations").fetchall()}
    assert "008_notification_cancels" not in versions
    assert "009_observability" not in versions


def test_valid_007_applies_008_009(scratch_dsn, tmp_path):
    """A valid 007 contract → 008 and 009 apply successfully."""
    partial = tmp_path / "migrations"
    partial.mkdir()
    for f in sorted(MIGRATIONS.glob("*.sql"))[:7]:
        (partial / f.name).write_bytes(f.read_bytes())
    assert migrate.run(partial) == 0

    # The 007 contract is intact — we run the full set.
    assert migrate.run(MIGRATIONS) == 0

    assert _count_migrations(scratch_dsn) == len(list(MIGRATIONS.glob("*.sql")))


# --- schema_verify directly -------------------------------------------------


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
    assert "009_observability" in joined  # missing
    assert "099_future" in joined         # foreign/future


def test_verify_contract_detects_dropped_index(scratch_dsn):
    assert migrate.run(MIGRATIONS) == 0
    with psycopg.connect(scratch_dsn, autocommit=True) as c:
        c.execute("DROP INDEX alerts_one_pending_per_subscription")
        problems = schema_verify.verify_contract(c)
    assert any("alerts_one_pending_per_subscription" in p for p in problems)


def test_verify_contract_detects_missing_subscriptions_unique(scratch_dsn):
    """Loss of UNIQUE(device_id, checkpoint_id, threshold) → verify_contract catches it.

    POST /subscriptions relies on ON CONFLICT (device_id, checkpoint_id, threshold);
    if the constraint was lost in the restore, the request would fail with an
    unexpected error in prod.
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
    """Turning a UNIQUE partial index into a regular one → verify_contract catches it.

    alerts_one_pending_per_subscription must be UNIQUE: without it, two pending
    alerts can be inserted for one subscription and the notifier would duplicate
    notifications.
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
    """Same-name UNIQUE partial index but with a different predicate → FAIL.

    Uniqueness+partial alone is not enough: a DROP+CREATE with the same name but a
    predicate `status = 'acknowledged'` instead of `status = 'pending'` holds a
    completely different invariant; the API would keep generating pending duplicates.
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
    """Same-name UNIQUE partial index on different columns → FAIL."""
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
    """Same-name UNIQUE constraint on different columns → FAIL.

    ON CONFLICT (device_id, checkpoint_id, threshold) in the API relies exactly on
    these columns; a constraint with the same name but (device_id) would fail in
    prod with an unexpected "no unique constraint matching..." error.
    """
    assert migrate.run(MIGRATIONS) == 0
    with psycopg.connect(scratch_dsn, autocommit=True) as c:
        c.execute(
            "ALTER TABLE subscriptions "
            "DROP CONSTRAINT subscriptions_device_id_checkpoint_id_threshold_key"
        )
        # We create a constraint with the same name but completely different columns.
        # First we must free device_id of duplicate values (in a clean DB it is empty).
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
    """DR contract: the real application comes up against a just-migrated DB with
    real data and passes prod-guard + health + auth + devices/secret + a protected
    request."""
    from avelren import db, restore_smoke

    monkeypatch.setenv("AVELREN_RESTORE_VERIFY_TARGET", "restore_test")
    monkeypatch.setenv("AVELREN_RESTORE_VERIFY_ROLE", "avelren_api")
    monkeypatch.setattr(restore_smoke, "dsn_identity_problems", lambda *_: [])

    assert migrate.run(MIGRATIONS) == 0

    # We seed the minimum data: checkpoint + observation. Without them /health
    # returns last_observation=null → smoke would fail on the DR gap check.
    with psycopg.connect(scratch_dsn, autocommit=True) as c:
        c.execute(
            "INSERT INTO checkpoints (id, title, for_vehicle_type) VALUES (1, 'Test', 0)"
        )
        c.execute(
            "INSERT INTO observations "
            "(time, checkpoint_id, wait_time_seconds, vehicles_in_queue, is_paused) "
            "VALUES (now(), 1, 60, 5, false)"
        )

    db._pool = None  # a fresh pool on the scratch DB specifically
    try:
        assert restore_smoke.main() == 0
    finally:
        db._pool = None


def test_restore_smoke_fails_on_empty_observations(scratch_dsn, monkeypatch):
    """Correct schema but zero data → smoke returns 1 (a DR false PASS is unacceptable).

    /health on AvelRen returns 200 even without observations; so smoke explicitly
    checks last_observation != null, to distinguish "restored" from "schema is
    there, no data".
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
    """Smoke refuses to run if current_database() == 'avelren'."""
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
    # The same DDL that migrate creates for the history table — so the test can
    # read it even when the migration did not reach creation.
    return migrate._SCHEMA
