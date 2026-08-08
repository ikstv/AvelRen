"""Least-privilege contracts exercised against disposable role DSNs."""

import os
import uuid
from contextlib import contextmanager

import psycopg
import pytest

RUNTIME_DSNS = (
    "COLLECTOR_DATABASE_URL",
    "NOTIFIER_DATABASE_URL",
    "WATCHDOG_DATABASE_URL",
    "API_DATABASE_URL",
)
RUNTIME_AND_BACKUP_DSNS = (*RUNTIME_DSNS, "BACKUP_DATABASE_URL")
RUNTIME_ROLES = {
    "COLLECTOR_DATABASE_URL": "avelren_collector",
    "NOTIFIER_DATABASE_URL": "avelren_notifier",
    "WATCHDOG_DATABASE_URL": "avelren_watchdog",
    "API_DATABASE_URL": "avelren_api",
}
SEQUENCES = (
    "alerts_id_seq",
    "eta_alerts_id_seq",
    "health_alerts_id_seq",
    "notification_cancels_id_seq",
    "subscriptions_id_seq",
    "eta_targets_id_seq",
)
USAGE_SEQUENCES = {
    "COLLECTOR_DATABASE_URL": {
        "alerts_id_seq",
        "eta_alerts_id_seq",
        "notification_cancels_id_seq",
    },
    "NOTIFIER_DATABASE_URL": set(),
    "WATCHDOG_DATABASE_URL": {"health_alerts_id_seq"},
    "API_DATABASE_URL": {
        "notification_cancels_id_seq",
        "subscriptions_id_seq",
        "eta_targets_id_seq",
    },
}


@contextmanager
def connect_env(name: str):
    with psycopg.connect(os.environ[name], autocommit=True) as conn:
        yield conn


def scalar(conn, sql: str, params: tuple[object, ...] = ()):
    return conn.execute(sql, params).fetchone()[0]


def assert_denied(dsn: str, sql: str) -> None:
    with connect_env(dsn) as conn:
        with pytest.raises(psycopg.Error) as raised:
            conn.execute(sql)
    assert raised.value.sqlstate == "42501"


@pytest.mark.parametrize("dsn_name", RUNTIME_AND_BACKUP_DSNS)
def test_role_has_no_elevated_capability(dsn_name):
    with connect_env(dsn_name) as conn:
        assert scalar(conn, "SELECT has_schema_privilege(current_user,'public','CREATE')") is False
        assert scalar(
            conn, "SELECT has_database_privilege(current_user,current_database(),'CREATE')"
        ) is False
        assert scalar(
            conn, "SELECT has_database_privilege(current_user,current_database(),'TEMP')"
        ) is False
        assert scalar(conn, "SELECT pg_has_role(current_user,'avelren_admin','MEMBER')") is False
        assert scalar(conn, "SELECT pg_has_role(current_user,'avelren_migrator','MEMBER')") is False


@pytest.mark.parametrize("dsn_name", RUNTIME_DSNS)
@pytest.mark.parametrize(
    "sql",
    (
        "CREATE ROLE avelren_ci_forbidden_role",
        "CREATE TABLE avelren_ci_forbidden_table (id integer)",
        "ALTER TABLE checkpoints ADD COLUMN avelren_ci_forbidden_column integer",
        "DROP TABLE checkpoints",
        "INSERT INTO schema_migrations (version, sha256) VALUES ('forbidden', 'forbidden')",
        "UPDATE schema_migrations SET sha256 = 'forbidden'",
        "DELETE FROM schema_migrations",
        "SET ROLE avelren_admin",
        "SET ROLE avelren_migrator",
    ),
)
def test_runtime_role_cannot_escalate_or_change_migration_history(dsn_name, sql):
    assert_denied(dsn_name, sql)


@pytest.mark.parametrize(
    ("dsn_name", "sql"),
    (
        ("API_DATABASE_URL", "UPDATE observations SET is_paused = false"),
        ("API_DATABASE_URL", "UPDATE collector_runs SET error = NULL"),
        ("API_DATABASE_URL", "UPDATE health_alerts SET detail = NULL"),
        ("COLLECTOR_DATABASE_URL", "SELECT * FROM devices"),
        ("COLLECTOR_DATABASE_URL", "UPDATE health_alerts SET detail = NULL"),
        ("COLLECTOR_DATABASE_URL", "SELECT * FROM notification_cancels"),
        ("COLLECTOR_DATABASE_URL", "UPDATE notification_cancels SET accepted_at = now()"),
        ("COLLECTOR_DATABASE_URL", "DELETE FROM notification_cancels"),
        ("NOTIFIER_DATABASE_URL", "UPDATE observations SET is_paused = false"),
        ("NOTIFIER_DATABASE_URL", "UPDATE collector_runs SET error = NULL"),
        ("NOTIFIER_DATABASE_URL", "UPDATE health_alerts SET detail = NULL"),
        ("NOTIFIER_DATABASE_URL", "SELECT secret_hash FROM devices"),
        ("NOTIFIER_DATABASE_URL", "SELECT is_admin FROM devices"),
        ("WATCHDOG_DATABASE_URL", "UPDATE alerts SET status = 'expired'"),
        ("WATCHDOG_DATABASE_URL", "UPDATE eta_alerts SET status = 'expired'"),
        ("WATCHDOG_DATABASE_URL", "UPDATE subscriptions SET is_active = false"),
        ("WATCHDOG_DATABASE_URL", "SELECT secret_hash FROM devices"),
        ("BACKUP_DATABASE_URL", "INSERT INTO countries (id, name) VALUES (1, 'forbidden')"),
        ("BACKUP_DATABASE_URL", "UPDATE countries SET name = 'forbidden'"),
        ("BACKUP_DATABASE_URL", "DELETE FROM countries"),
        ("BACKUP_DATABASE_URL", "CREATE TABLE avelren_ci_backup_table (id integer)"),
        ("BACKUP_DATABASE_URL", "ALTER TABLE countries ADD COLUMN avelren_ci_column integer"),
        ("BACKUP_DATABASE_URL", "DROP TABLE countries"),
    ),
)
def test_role_specific_negative_matrix(dsn_name, sql):
    assert_denied(dsn_name, sql)


@pytest.mark.parametrize("dsn_name", RUNTIME_DSNS)
def test_runtime_sequence_usage_is_exact(dsn_name):
    expected = USAGE_SEQUENCES[dsn_name]
    with connect_env(dsn_name) as conn:
        for sequence in SEQUENCES:
            assert scalar(
                conn,
                "SELECT has_sequence_privilege(current_user, %s, 'USAGE')",
                (sequence,),
            ) is (sequence in expected)


def test_backup_has_read_only_sequence_access():
    with connect_env("BACKUP_DATABASE_URL") as conn:
        for sequence in SEQUENCES:
            assert scalar(
                conn,
                "SELECT has_sequence_privilege(current_user, %s, 'SELECT')",
                (sequence,),
            ) is True
            assert scalar(
                conn,
                "SELECT has_sequence_privilege(current_user, %s, 'USAGE')",
                (sequence,),
            ) is False


def test_migrator_default_privileges_isolate_future_objects():
    suffix = uuid.uuid4().hex
    table = f"avelren_ci_future_table_{suffix}"
    function = f"avelren_ci_future_function_{suffix}"
    enum = f"avelren_ci_future_enum_{suffix}"
    signature = f"public.{function}()"
    type_name = f"public.{enum}"

    with connect_env("MIGRATOR_DATABASE_URL") as migrator:
        migrator.execute(f"CREATE TABLE {table} (id integer)")
        migrator.execute(f"CREATE FUNCTION {function}() RETURNS integer LANGUAGE sql AS 'SELECT 1'")
        migrator.execute(f"CREATE TYPE {enum} AS ENUM ('value')")
        try:
            with connect_env("ADMIN_DATABASE_URL") as admin:
                for dsn_name in RUNTIME_DSNS:
                    assert scalar(
                        admin,
                        "SELECT has_table_privilege(%s, %s, 'SELECT')",
                        (RUNTIME_ROLES[dsn_name], table),
                    ) is False
                assert scalar(
                    admin,
                    "SELECT has_function_privilege('public', %s, 'EXECUTE')",
                    (signature,),
                ) is False
                assert scalar(
                    admin,
                    "SELECT has_type_privilege('public', %s, 'USAGE')",
                    (type_name,),
                ) is False
        finally:
            migrator.execute(f"DROP FUNCTION IF EXISTS {function}()")
            migrator.execute(f"DROP TABLE IF EXISTS {table}")
            migrator.execute(f"DROP TYPE IF EXISTS {enum}")
