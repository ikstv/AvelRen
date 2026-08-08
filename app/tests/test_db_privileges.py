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
APPLICATION_TABLES = (
    "countries",
    "checkpoints",
    "observations",
    "observations_hourly",
    "collector_runs",
    "devices",
    "subscriptions",
    "subscription_state",
    "alerts",
    "eta_targets",
    "eta_alerts",
    "health_alerts",
    "notification_cancels",
    "schema_migrations",
)
TABLE_PRIVILEGES = (
    "SELECT",
    "INSERT",
    "UPDATE",
    "DELETE",
    "TRUNCATE",
    "REFERENCES",
    "TRIGGER",
)
SEQUENCE_PRIVILEGES = ("USAGE", "SELECT", "UPDATE")
SEQUENCES = (
    "alerts_id_seq",
    "eta_alerts_id_seq",
    "health_alerts_id_seq",
    "notification_cancels_id_seq",
    "subscriptions_id_seq",
    "eta_targets_id_seq",
)
EXPECTED_TABLE_PRIVILEGES = {
    "BACKUP_DATABASE_URL": {table: {"SELECT"} for table in APPLICATION_TABLES},
    "COLLECTOR_DATABASE_URL": {
        "countries": {"SELECT", "INSERT", "UPDATE"},
        "checkpoints": {"SELECT", "INSERT", "UPDATE"},
        "observations": {"SELECT", "INSERT", "UPDATE"},
        "collector_runs": {"SELECT", "INSERT", "UPDATE"},
        "subscriptions": {"SELECT"},
        "subscription_state": {"SELECT", "INSERT", "UPDATE"},
        "alerts": {"SELECT", "INSERT", "UPDATE"},
        "eta_targets": {"SELECT", "INSERT", "UPDATE"},
        "eta_alerts": {"SELECT", "INSERT", "UPDATE"},
        "notification_cancels": {"INSERT"},
    },
    "NOTIFIER_DATABASE_URL": {
        "alerts": {"SELECT"},
        "eta_alerts": {"SELECT"},
        "subscriptions": {"SELECT"},
        "eta_targets": {"SELECT"},
        "checkpoints": {"SELECT"},
        "notification_cancels": {"SELECT", "DELETE"},
    },
    "WATCHDOG_DATABASE_URL": {
        "observations": {"SELECT"},
        "collector_runs": {"SELECT"},
        "health_alerts": {"SELECT", "INSERT", "UPDATE"},
    },
    "API_DATABASE_URL": {
        "countries": {"SELECT"},
        "checkpoints": {"SELECT"},
        "observations": {"SELECT"},
        "observations_hourly": {"SELECT"},
        "collector_runs": {"SELECT"},
        "subscriptions": {"SELECT", "INSERT", "UPDATE", "DELETE"},
        "alerts": {"SELECT"},
        "eta_targets": {"SELECT", "INSERT", "UPDATE", "DELETE"},
        "eta_alerts": {"SELECT"},
        "health_alerts": {"SELECT"},
        "notification_cancels": {"INSERT"},
    },
}
EXPECTED_SEQUENCE_PRIVILEGES = {
    "BACKUP_DATABASE_URL": {sequence: {"SELECT"} for sequence in SEQUENCES},
    "COLLECTOR_DATABASE_URL": {
        "alerts_id_seq": {"USAGE"},
        "eta_alerts_id_seq": {"USAGE"},
        "notification_cancels_id_seq": {"USAGE"},
    },
    "NOTIFIER_DATABASE_URL": {},
    "WATCHDOG_DATABASE_URL": {"health_alerts_id_seq": {"USAGE"}},
    "API_DATABASE_URL": {
        "notification_cancels_id_seq": {"USAGE"},
        "subscriptions_id_seq": {"USAGE"},
        "eta_targets_id_seq": {"USAGE"},
    },
}
EXPECTED_DEVICE_COLUMN_PRIVILEGES = {
    "BACKUP_DATABASE_URL": {
        column: {"SELECT"}
        for column in (
            "id",
            "fcm_token",
            "platform",
            "created_at",
            "last_seen",
            "is_admin",
            "secret_hash",
        )
    },
    "COLLECTOR_DATABASE_URL": {},
    "NOTIFIER_DATABASE_URL": {"id": {"SELECT"}, "fcm_token": {"SELECT", "UPDATE"}},
    "WATCHDOG_DATABASE_URL": {
        "id": {"SELECT"},
        "is_admin": {"SELECT"},
        "fcm_token": {"SELECT"},
    },
    "API_DATABASE_URL": {
        "id": {"SELECT"},
        "fcm_token": {"SELECT", "INSERT", "UPDATE"},
        "platform": {"SELECT", "INSERT"},
        "secret_hash": {"SELECT", "INSERT"},
        "is_admin": {"SELECT"},
        "last_seen": {"SELECT", "UPDATE"},
    },
}
COLUMN_UPDATE_PRIVILEGES = {
    "NOTIFIER_DATABASE_URL": {
        "alerts": {"last_sent_at", "send_count"},
        "eta_alerts": {"last_sent_at", "send_count"},
        "notification_cancels": {"attempt_count", "last_attempt_at", "accepted_at", "abandoned_at"},
    },
    "API_DATABASE_URL": {
        "alerts": {"status", "acknowledged_at"},
        "eta_alerts": {"status", "acknowledged_at"},
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


@pytest.mark.parametrize("dsn_name", RUNTIME_AND_BACKUP_DSNS)
def test_table_privileges_match_frozen_acl(dsn_name):
    expected = EXPECTED_TABLE_PRIVILEGES[dsn_name]
    with connect_env(dsn_name) as conn:
        for table in APPLICATION_TABLES:
            actual = {
                privilege
                for privilege in TABLE_PRIVILEGES
                if scalar(
                    conn,
                    "SELECT has_table_privilege(current_user, %s, %s)",
                    (table, privilege),
                )
            }
            assert actual == expected.get(table, set())


@pytest.mark.parametrize("dsn_name", RUNTIME_AND_BACKUP_DSNS)
def test_sequence_privileges_match_frozen_acl(dsn_name):
    expected = EXPECTED_SEQUENCE_PRIVILEGES[dsn_name]
    with connect_env(dsn_name) as conn:
        for sequence in SEQUENCES:
            actual = {
                privilege
                for privilege in SEQUENCE_PRIVILEGES
                if scalar(
                    conn,
                    "SELECT has_sequence_privilege(current_user, %s, %s)",
                    (sequence, privilege),
                )
            }
            assert actual == expected.get(sequence, set())


@pytest.mark.parametrize("dsn_name", RUNTIME_AND_BACKUP_DSNS)
def test_device_column_privileges_match_frozen_acl(dsn_name):
    expected = EXPECTED_DEVICE_COLUMN_PRIVILEGES[dsn_name]
    with connect_env(dsn_name) as conn:
        for column in (
            "id",
            "fcm_token",
            "platform",
            "created_at",
            "last_seen",
            "is_admin",
            "secret_hash",
        ):
            actual = {
                privilege
                for privilege in ("SELECT", "INSERT", "UPDATE")
                if scalar(
                    conn,
                    "SELECT has_column_privilege(current_user, 'devices', %s, %s)",
                    (column, privilege),
                )
            }
            assert actual == expected.get(column, set())


@pytest.mark.parametrize("dsn_name", ("NOTIFIER_DATABASE_URL", "API_DATABASE_URL"))
def test_column_scoped_updates_match_frozen_acl(dsn_name):
    expected_tables = COLUMN_UPDATE_PRIVILEGES[dsn_name]
    with connect_env(dsn_name) as conn:
        for table, expected in expected_tables.items():
            columns = [
                row[0]
                for row in conn.execute(
                    "SELECT attname FROM pg_attribute "
                    "WHERE attrelid = %s::regclass AND attnum > 0 AND NOT attisdropped",
                    (table,),
                )
            ]
            actual = {
                column
                for column in columns
                if scalar(
                    conn,
                    "SELECT has_column_privilege(current_user, %s, %s, 'UPDATE')",
                    (table, column),
                )
            }
            assert actual == expected


def test_public_has_no_existing_application_object_privileges():
    with connect_env("ADMIN_DATABASE_URL") as admin:
        for table in APPLICATION_TABLES:
            for privilege in TABLE_PRIVILEGES:
                assert scalar(
                    admin,
                    "SELECT has_table_privilege('public', %s, %s)",
                    (table, privilege),
                ) is False
        for sequence in SEQUENCES:
            for privilege in SEQUENCE_PRIVILEGES:
                assert scalar(
                    admin,
                    "SELECT has_sequence_privilege('public', %s, %s)",
                    (sequence, privilege),
                ) is False


def test_migrator_default_privileges_isolate_future_objects():
    suffix = uuid.uuid4().hex
    table = f"avelren_ci_future_table_{suffix}"
    function = f"avelren_ci_future_function_{suffix}"
    enum = f"avelren_ci_future_enum_{suffix}"
    signature = f"public.{function}()"
    type_name = f"public.{enum}"

    with connect_env("MIGRATOR_DATABASE_URL") as migrator:
        try:
            migrator.execute(f"CREATE TABLE {table} (id integer)")
            migrator.execute(
                f"CREATE FUNCTION {function}() RETURNS integer LANGUAGE sql AS 'SELECT 1'"
            )
            migrator.execute(f"CREATE TYPE {enum} AS ENUM ('value')")
            with connect_env("ADMIN_DATABASE_URL") as admin:
                for role in (*RUNTIME_ROLES.values(), "public"):
                    for privilege in TABLE_PRIVILEGES:
                        assert scalar(
                            admin,
                            "SELECT has_table_privilege(%s, %s, %s)",
                            (role, table, privilege),
                        ) is False
                for role in (*RUNTIME_ROLES.values(), "public"):
                    assert scalar(
                        admin,
                        "SELECT has_function_privilege(%s, %s, 'EXECUTE')",
                        (role, signature),
                    ) is False
                    assert scalar(
                        admin,
                        "SELECT has_type_privilege(%s, %s, 'USAGE')",
                        (role, type_name),
                    ) is False
        finally:
            try:
                migrator.execute(f"DROP FUNCTION IF EXISTS {function}()")
            finally:
                try:
                    migrator.execute(f"DROP TABLE IF EXISTS {table}")
                finally:
                    migrator.execute(f"DROP TYPE IF EXISTS {enum}")
