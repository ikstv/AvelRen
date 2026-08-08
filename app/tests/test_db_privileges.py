"""Least-privilege contracts exercised against disposable role DSNs."""

import asyncio
import os
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient

from avelren import alerts, cancels, db, eta, notifier, watchdog
from avelren.api import app
from avelren.config import settings
from avelren.models import Country, WorkloadItem

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
COLUMN_SELECT_PRIVILEGES = {
    "COLLECTOR_DATABASE_URL": {"notification_cancels": {"kind", "alert_id"}},
    "API_DATABASE_URL": {"notification_cancels": {"kind", "alert_id"}},
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


@contextmanager
def privilege_path(role: str, operation: str, object_name: str):
    """Report only the missing capability, never the role DSN."""
    try:
        yield
    except psycopg.errors.InsufficientPrivilege as exc:
        actual_object = exc.diag.table_name or exc.diag.column_name or object_name
        pytest.fail(
            f"{role}: {operation} on {actual_object}: {exc.diag.message_primary}",
            pytrace=False,
        )


async def run_with_role_pool(dsn_name: str, operation):
    """Run a real service operation through the role-configured application pool."""
    previous_url = settings.database_url
    settings.database_url = os.environ[dsn_name]
    db._pool = None
    pool = db.get_pool()
    await pool.open(wait=True, timeout=30)
    try:
        return await operation(pool)
    finally:
        await pool.close()
        db._pool = None
        settings.database_url = previous_url


def synthetic_id() -> int:
    return 1_000_000_000 + uuid.uuid4().int % 1_000_000_000


def device_headers(device_id: str, secret: str) -> dict[str, str]:
    return {"X-Device-Id": device_id, "X-Device-Secret": secret}


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


@pytest.mark.parametrize("dsn_name", ("COLLECTOR_DATABASE_URL", "API_DATABASE_URL"))
def test_column_scoped_selects_match_frozen_acl(dsn_name):
    expected_tables = COLUMN_SELECT_PRIVILEGES[dsn_name]
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
                    "SELECT has_column_privilege(current_user, %s, %s, 'SELECT')",
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


def test_collector_positive_service_paths_commit_without_device_access():
    role = "avelren_collector"
    existing_country_id = synthetic_id()
    new_country_id = synthetic_id()
    existing_checkpoint_id = synthetic_id()
    new_checkpoint_id = synthetic_id()
    device_id = str(uuid.uuid4())
    observed_at = datetime.now(UTC) - timedelta(hours=2)
    expires_at = datetime.now(UTC)

    with connect_env("ADMIN_DATABASE_URL") as admin:
        admin.execute(
            "INSERT INTO countries (id, name) VALUES (%s, 'seed-country')",
            (existing_country_id,),
        )
        admin.execute(
            "INSERT INTO checkpoints (id, title, country_id, for_vehicle_type) "
            "VALUES (%s, 'seed-checkpoint', %s, 1)",
            (existing_checkpoint_id, existing_country_id),
        )
        admin.execute("INSERT INTO devices (id) VALUES (%s)", (device_id,))
        subscription_id = admin.execute(
            "INSERT INTO subscriptions (device_id, checkpoint_id, threshold) "
            "VALUES (%s, %s, 50) RETURNING id",
            (device_id, existing_checkpoint_id),
        ).fetchone()[0]
        target_id = admin.execute(
            "INSERT INTO eta_targets (device_id, checkpoint_id, target_at) "
            "VALUES (%s, %s, %s) RETURNING id",
            (device_id, existing_checkpoint_id, observed_at + timedelta(hours=1)),
        ).fetchone()[0]

    countries = [
        Country(id=existing_country_id, name="updated-country"),
        Country(id=new_country_id, name="inserted-country"),
    ]
    high_items = [
        WorkloadItem(
            id=existing_checkpoint_id,
            title="updated-checkpoint",
            country_id=existing_country_id,
            for_vehicle_type=1,
            wait_time=3600,
            vehicle_in_active_queues_counts=100,
        ),
        WorkloadItem(
            id=new_checkpoint_id,
            title="inserted-checkpoint",
            country_id=new_country_id,
            for_vehicle_type=1,
            wait_time=60,
            vehicle_in_active_queues_counts=5,
        ),
    ]
    low_item = WorkloadItem(
        id=existing_checkpoint_id,
        title="updated-checkpoint",
        country_id=existing_country_id,
        for_vehicle_type=1,
        wait_time=60,
        vehicle_in_active_queues_counts=10,
    )

    async def exercise(pool):
        async with pool.connection() as conn:
            with privilege_path(role, "UPSERT", "countries"):
                await db.upsert_countries(conn, countries)
            with privilege_path(role, "UPSERT", "checkpoints"):
                await db.upsert_checkpoints(conn, high_items, countries)
            with privilege_path(role, "INSERT", "observations"):
                assert await db.insert_observations(conn, observed_at, high_items) == 2
            with privilege_path(role, "INSERT", "collector_runs"):
                await db.record_run(conn, observed_at, 200, 12, "positive", 2, None)
            with privilege_path(role, "threshold evaluation", "subscriptions/alerts"):
                assert await alerts.evaluate(conn, high_items) == 1
            with privilege_path(role, "ETA evaluation", "eta_targets/eta_alerts"):
                assert await eta.evaluate(conn, observed_at, high_items) == 1
            with privilege_path(role, "INSERT", "observations"):
                assert await db.insert_observations(conn, expires_at, [low_item]) == 1
            with privilege_path(role, "expire and enqueue", "alerts/notification_cancels"):
                assert await alerts.expire_stale(conn) == 1
            with privilege_path(role, "expire and enqueue", "eta_targets/notification_cancels"):
                assert await eta.expire_passed(conn) == 1
            with privilege_path(role, "UPDATE", "collector_runs"):
                await db.record_derived(conn, observed_at, None)

    try:
        asyncio.run(run_with_role_pool("COLLECTOR_DATABASE_URL", exercise))

        with connect_env("ADMIN_DATABASE_URL") as admin:
            assert scalar(
                admin, "SELECT count(*) FROM countries WHERE id IN (%s, %s)",
                (existing_country_id, new_country_id),
            ) == 2
            assert scalar(
                admin, "SELECT count(*) FROM checkpoints WHERE id IN (%s, %s)",
                (existing_checkpoint_id, new_checkpoint_id),
            ) == 2
            assert scalar(
                admin, "SELECT count(*) FROM observations WHERE checkpoint_id IN (%s, %s)",
                (existing_checkpoint_id, new_checkpoint_id),
            ) == 3
            assert scalar(
                admin,
                "SELECT derived_processed_at IS NOT NULL FROM collector_runs WHERE time = %s",
                (observed_at,),
            ) is True
            assert scalar(
                admin, "SELECT status FROM alerts WHERE subscription_id = %s", (subscription_id,)
            ) == "expired"
            assert scalar(
                admin, "SELECT status FROM eta_alerts WHERE target_id = %s", (target_id,)
            ) == "expired"
            assert scalar(
                admin,
                "SELECT count(*) FROM notification_cancels WHERE device_id = %s",
                (device_id,),
            ) == 2

        assert_denied("COLLECTOR_DATABASE_URL", "SELECT id FROM devices")
    finally:
        with connect_env("ADMIN_DATABASE_URL") as admin:
            admin.execute("DELETE FROM devices WHERE id = %s", (device_id,))
            admin.execute(
                "DELETE FROM observations WHERE checkpoint_id IN (%s, %s)",
                (existing_checkpoint_id, new_checkpoint_id),
            )
            admin.execute("DELETE FROM collector_runs WHERE time = %s", (observed_at,))
            admin.execute(
                "DELETE FROM checkpoints WHERE id IN (%s, %s)",
                (existing_checkpoint_id, new_checkpoint_id),
            )
            admin.execute(
                "DELETE FROM countries WHERE id IN (%s, %s)",
                (existing_country_id, new_country_id),
            )


def test_notifier_positive_service_paths_cover_delivery_and_cancel_lifecycle():
    role = "avelren_notifier"
    checkpoint_id = synthetic_id()
    live_device = str(uuid.uuid4())
    dead_device = str(uuid.uuid4())
    retry_device = str(uuid.uuid4())
    empty_device = str(uuid.uuid4())

    with connect_env("ADMIN_DATABASE_URL") as admin:
        admin.execute(
            "INSERT INTO checkpoints (id, title, for_vehicle_type) VALUES (%s, 'notify', 1)",
            (checkpoint_id,),
        )
        admin.execute(
            "INSERT INTO devices (id, fcm_token) VALUES "
            "(%s, 'positive-live'), (%s, 'positive-dead'), "
            "(%s, 'positive-retry'), (%s, NULL)",
            (live_device, dead_device, retry_device, empty_device),
        )
        live_subscription = admin.execute(
            "INSERT INTO subscriptions (device_id, checkpoint_id, threshold) "
            "VALUES (%s, %s, 50) RETURNING id",
            (live_device, checkpoint_id),
        ).fetchone()[0]
        dead_subscription = admin.execute(
            "INSERT INTO subscriptions (device_id, checkpoint_id, threshold) "
            "VALUES (%s, %s, 100) RETURNING id",
            (dead_device, checkpoint_id),
        ).fetchone()[0]
        live_alert = admin.execute(
            "INSERT INTO alerts (subscription_id, checkpoint_id, threshold, vehicles_at_trigger) "
            "VALUES (%s, %s, 50, 75) RETURNING id",
            (live_subscription, checkpoint_id),
        ).fetchone()[0]
        dead_alert = admin.execute(
            "INSERT INTO alerts (subscription_id, checkpoint_id, threshold, vehicles_at_trigger) "
            "VALUES (%s, %s, 100, 125) RETURNING id",
            (dead_subscription, checkpoint_id),
        ).fetchone()[0]
        live_target = admin.execute(
            "INSERT INTO eta_targets (device_id, checkpoint_id, target_at) "
            "VALUES (%s, %s, now() + INTERVAL '1 hour') RETURNING id",
            (live_device, checkpoint_id),
        ).fetchone()[0]
        live_eta_alert = admin.execute(
            "INSERT INTO eta_alerts "
            "(target_id, checkpoint_id, eta_at_trigger, wait_seconds_at_trigger) "
            "VALUES (%s, %s, now() + INTERVAL '1 hour', 3600) RETURNING id",
            (live_target, checkpoint_id),
        ).fetchone()[0]
        accepted_cancel = admin.execute(
            "INSERT INTO notification_cancels (kind, alert_id, device_id) "
            "VALUES ('threshold', %s, %s) RETURNING id",
            (synthetic_id(), live_device),
        ).fetchone()[0]
        retry_cancel = admin.execute(
            "INSERT INTO notification_cancels (kind, alert_id, device_id) "
            "VALUES ('threshold', %s, %s) RETURNING id",
            (synthetic_id(), retry_device),
        ).fetchone()[0]
        abandoned_cancel = admin.execute(
            "INSERT INTO notification_cancels (kind, alert_id, device_id) "
            "VALUES ('eta', %s, %s) RETURNING id",
            (synthetic_id(), empty_device),
        ).fetchone()[0]
        cleanup_cancel = admin.execute(
            "INSERT INTO notification_cancels "
            "(kind, alert_id, device_id, created_at, accepted_at) "
            "VALUES ('eta', %s, %s, now() - INTERVAL '2 days', now()) RETURNING id",
            (synthetic_id(), live_device),
        ).fetchone()[0]

    async def exercise(pool):
        async with pool.connection() as conn:
            with privilege_path(role, "pending SELECT", "alerts/eta_alerts/devices"):
                rows = await (
                    await conn.execute(notifier._QUERY, {"gap": "300 seconds"})
                ).fetchall()
            assert {(row["kind"], row["id"]) for row in rows} == {
                ("threshold", live_alert),
                ("threshold", dead_alert),
                ("eta", live_eta_alert),
            }
            with privilege_path(role, "delivery UPDATE", "alerts"):
                await notifier._mark_sent(conn, "threshold", live_alert)
            with privilege_path(role, "delivery UPDATE", "eta_alerts"):
                await notifier._mark_sent(conn, "eta", live_eta_alert)
            with privilege_path(role, "dead-token UPDATE", "devices.fcm_token"):
                await notifier._disable_device(conn, dead_device)
            with privilege_path(role, "open-cancel SELECT", "notification_cancels/devices"):
                open_cancels = await cancels.fetch_open(conn)
            assert {row["id"] for row in open_cancels} >= {
                accepted_cancel,
                retry_cancel,
                abandoned_cancel,
            }
            with privilege_path(role, "attempt UPDATE", "notification_cancels"):
                await cancels.record_attempt(conn, retry_cancel)
            with privilege_path(role, "accept UPDATE", "notification_cancels"):
                await cancels.mark_accepted(conn, accepted_cancel)
            with privilege_path(role, "abandon UPDATE", "notification_cancels"):
                await cancels.mark_abandoned(conn, abandoned_cancel)
            with privilege_path(role, "cleanup DELETE", "notification_cancels"):
                await cancels.cleanup_closed(conn)

    try:
        asyncio.run(run_with_role_pool("NOTIFIER_DATABASE_URL", exercise))

        with connect_env("ADMIN_DATABASE_URL") as admin:
            assert scalar(admin, "SELECT send_count FROM alerts WHERE id = %s", (live_alert,)) == 1
            assert scalar(
                admin, "SELECT send_count FROM eta_alerts WHERE id = %s", (live_eta_alert,)
            ) == 1
            assert scalar(
                admin, "SELECT fcm_token FROM devices WHERE id = %s", (dead_device,)
            ) is None
            assert scalar(
                admin,
                "SELECT accepted_at IS NOT NULL FROM notification_cancels WHERE id = %s",
                (accepted_cancel,),
            ) is True
            assert scalar(
                admin,
                "SELECT attempt_count FROM notification_cancels WHERE id = %s",
                (retry_cancel,),
            ) == 1
            assert scalar(
                admin,
                "SELECT abandoned_at IS NOT NULL FROM notification_cancels WHERE id = %s",
                (abandoned_cancel,),
            ) is True
            assert scalar(
                admin, "SELECT count(*) FROM notification_cancels WHERE id = %s", (cleanup_cancel,)
            ) == 0

        assert_denied("NOTIFIER_DATABASE_URL", "UPDATE health_alerts SET detail = NULL")
    finally:
        with connect_env("ADMIN_DATABASE_URL") as admin:
            admin.execute(
                "DELETE FROM devices WHERE id IN (%s, %s, %s, %s)",
                (live_device, dead_device, retry_device, empty_device),
            )
            admin.execute("DELETE FROM checkpoints WHERE id = %s", (checkpoint_id,))


def test_watchdog_positive_service_paths_cover_health_and_recovery(monkeypatch):
    role = "avelren_watchdog"
    device_id = str(uuid.uuid4())
    checkpoint_id = synthetic_id()

    async def fake_send(*args, **kwargs):
        return None

    monkeypatch.setattr("avelren.fcm.send", fake_send)
    with connect_env("ADMIN_DATABASE_URL") as admin:
        admin.execute(
            "INSERT INTO devices (id, fcm_token, is_admin) VALUES (%s, 'positive-admin', true)",
            (device_id,),
        )

    async def exercise(pool):
        with privilege_path(role, "health SELECT/INSERT/UPDATE", "health_alerts"):
            await watchdog.run_cycle(client=None)

    health_id = None
    try:
        asyncio.run(run_with_role_pool("WATCHDOG_DATABASE_URL", exercise))
        with connect_env("ADMIN_DATABASE_URL") as admin:
            row = admin.execute(
                "SELECT id, send_count, resolved_at FROM health_alerts "
                "WHERE kind = 'no_data' AND resolved_at IS NULL"
            ).fetchone()
            assert row is not None
            health_id = row[0]
            assert row[1] == 1
            admin.execute(
                "INSERT INTO checkpoints (id, title, for_vehicle_type) VALUES (%s, 'watchdog', 1)",
                (checkpoint_id,),
            )
            admin.execute(
                "INSERT INTO observations "
                "(time, checkpoint_id, wait_time_seconds, vehicles_in_queue, is_paused) "
                "VALUES (now(), %s, 60, 5, false)",
                (checkpoint_id,),
            )

        asyncio.run(run_with_role_pool("WATCHDOG_DATABASE_URL", exercise))
        with connect_env("ADMIN_DATABASE_URL") as admin:
            row = admin.execute(
                "SELECT resolved_at, recovery_notified_at FROM health_alerts WHERE id = %s",
                (health_id,),
            ).fetchone()
            assert row[0] is not None
            assert row[1] is not None

        assert_denied("WATCHDOG_DATABASE_URL", "UPDATE alerts SET status = 'expired'")
    finally:
        with connect_env("ADMIN_DATABASE_URL") as admin:
            if health_id is not None:
                admin.execute("DELETE FROM health_alerts WHERE id = %s", (health_id,))
            admin.execute("DELETE FROM devices WHERE id = %s", (device_id,))
            admin.execute("DELETE FROM observations WHERE checkpoint_id = %s", (checkpoint_id,))
            admin.execute("DELETE FROM checkpoints WHERE id = %s", (checkpoint_id,))


def test_api_positive_routes_use_api_role_for_reads_and_lifecycles():
    role = "avelren_api"
    checkpoint_id = synthetic_id()
    health_kind = f"privilege-positive-{uuid.uuid4().hex}"
    device_id = None
    health_id = None

    with connect_env("ADMIN_DATABASE_URL") as admin:
        admin.execute(
            "INSERT INTO checkpoints (id, title, for_vehicle_type, country_name) "
            "VALUES (%s, 'api-positive', 1, 'test')",
            (checkpoint_id,),
        )
        admin.execute(
            "INSERT INTO observations "
            "(time, checkpoint_id, wait_time_seconds, vehicles_in_queue, is_paused) "
            "VALUES (now(), %s, 3600, 75, false)",
            (checkpoint_id,),
        )
        health_id = admin.execute(
            "INSERT INTO health_alerts (kind, detail) VALUES (%s, 'positive') RETURNING id",
            (health_kind,),
        ).fetchone()[0]

    previous_url = settings.database_url
    settings.database_url = os.environ["API_DATABASE_URL"]
    db._pool = None
    try:
        with TestClient(app) as client:
            with privilege_path(role, "health SELECT", "observations"):
                assert client.get("/health").status_code == 200
            with privilege_path(role, "checkpoint SELECT", "checkpoints"):
                checkpoints_response = client.get("/checkpoints")
            assert checkpoints_response.status_code == 200
            assert checkpoint_id in {row["id"] for row in checkpoints_response.json()}
            with privilege_path(role, "workload SELECT", "observations/checkpoints"):
                workload_response = client.get("/workload")
            assert workload_response.status_code == 200
            assert checkpoint_id in {row["checkpoint_id"] for row in workload_response.json()}
            with privilege_path(role, "history SELECT", "observations/checkpoints"):
                history_response = client.get(f"/history/{checkpoint_id}")
            assert history_response.status_code == 200
            assert history_response.json()["resolution"] == "raw"

            with privilege_path(role, "device INSERT", "devices"):
                registration = client.post(
                    "/devices",
                    json={"fcm_token": f"api-positive-{uuid.uuid4().hex}"},
                )
            assert registration.status_code == 201
            device_id = registration.json()["device_id"]
            secret = registration.json()["device_secret"]
            headers = device_headers(device_id, secret)
            with connect_env("ADMIN_DATABASE_URL") as admin:
                admin.execute("UPDATE devices SET is_admin = true WHERE id = %s", (device_id,))

            with privilege_path(role, "device authentication", "devices"):
                assert client.get("/subscriptions", headers=headers).status_code == 200
            with privilege_path(role, "subscription INSERT", "subscriptions"):
                subscription = client.post(
                    "/subscriptions",
                    json={"checkpoint_id": checkpoint_id, "threshold": 50},
                    headers=headers,
                )
            assert subscription.status_code == 201
            subscription_id = subscription.json()["id"]
            with privilege_path(role, "subscription SELECT", "subscriptions/alerts"):
                listed = client.get("/subscriptions", headers=headers)
            assert listed.status_code == 200
            assert subscription_id in {row["id"] for row in listed.json()}
            with connect_env("ADMIN_DATABASE_URL") as admin:
                alert_id = admin.execute(
                    "INSERT INTO alerts "
                    "(subscription_id, checkpoint_id, threshold, vehicles_at_trigger) "
                    "VALUES (%s, %s, 50, 75) RETURNING id",
                    (subscription_id, checkpoint_id),
                ).fetchone()[0]
            with privilege_path(role, "alert acknowledgement UPDATE", "alerts"):
                acknowledged = client.post(f"/alerts/{alert_id}/ack", headers=headers)
            assert acknowledged.json() == {"status": "acknowledged"}

            with privilege_path(role, "subscription INSERT", "subscriptions"):
                deletable_subscription = client.post(
                    "/subscriptions",
                    json={"checkpoint_id": checkpoint_id, "threshold": 100},
                    headers=headers,
                )
            deletable_subscription_id = deletable_subscription.json()["id"]
            with connect_env("ADMIN_DATABASE_URL") as admin:
                deleted_alert_id = admin.execute(
                    "INSERT INTO alerts "
                    "(subscription_id, checkpoint_id, threshold, vehicles_at_trigger) "
                    "VALUES (%s, %s, 100, 125) RETURNING id",
                    (deletable_subscription_id, checkpoint_id),
                ).fetchone()[0]
            with privilege_path(role, "subscription DELETE/cancel INSERT", "subscriptions"):
                deleted = client.delete(
                    f"/subscriptions/{deletable_subscription_id}", headers=headers
                )
            assert deleted.status_code == 204

            target_time = datetime.now(UTC) + timedelta(hours=4)
            with privilege_path(role, "ETA target INSERT", "eta_targets"):
                target = client.post(
                    "/eta-targets",
                    json={"checkpoint_id": checkpoint_id, "target_at": target_time.isoformat()},
                    headers=headers,
                )
            assert target.status_code == 201
            target_id = target.json()["id"]
            with privilege_path(role, "ETA target SELECT", "eta_targets/eta_alerts"):
                listed_targets = client.get("/eta-targets", headers=headers)
            assert target_id in {row["id"] for row in listed_targets.json()}
            with connect_env("ADMIN_DATABASE_URL") as admin:
                eta_alert_id = admin.execute(
                    "INSERT INTO eta_alerts "
                    "(target_id, checkpoint_id, eta_at_trigger, wait_seconds_at_trigger) "
                    "VALUES (%s, %s, %s, 3600) RETURNING id",
                    (target_id, checkpoint_id, target_time),
                ).fetchone()[0]
            with privilege_path(role, "ETA acknowledgement UPDATE", "eta_alerts/eta_targets"):
                eta_acknowledged = client.post(
                    f"/eta-alerts/{eta_alert_id}/ack", headers=headers
                )
            assert eta_acknowledged.json() == {"status": "acknowledged"}

            delete_target_time = datetime.now(UTC) + timedelta(hours=5)
            with privilege_path(role, "ETA target INSERT", "eta_targets"):
                deletable_target = client.post(
                    "/eta-targets",
                    json={
                        "checkpoint_id": checkpoint_id,
                        "target_at": delete_target_time.isoformat(),
                    },
                    headers=headers,
                )
            deletable_target_id = deletable_target.json()["id"]
            with connect_env("ADMIN_DATABASE_URL") as admin:
                deleted_eta_alert_id = admin.execute(
                    "INSERT INTO eta_alerts "
                    "(target_id, checkpoint_id, eta_at_trigger, wait_seconds_at_trigger) "
                    "VALUES (%s, %s, %s, 3600) RETURNING id",
                    (deletable_target_id, checkpoint_id, delete_target_time),
                ).fetchone()[0]
            with privilege_path(role, "ETA target DELETE/cancel INSERT", "eta_targets"):
                deleted_target = client.delete(
                    f"/eta-targets/{deletable_target_id}", headers=headers
                )
            assert deleted_target.status_code == 204

            with privilege_path(role, "admin telemetry SELECT", "application tables"):
                telemetry_response = client.get("/admin/telemetry", headers=headers)
            assert telemetry_response.status_code == 200
            assert health_kind in {
                problem["kind"] for problem in telemetry_response.json()["problems"]
            }

        with connect_env("ADMIN_DATABASE_URL") as admin:
            assert scalar(admin, "SELECT status FROM alerts WHERE id = %s", (alert_id,)) == (
                "acknowledged"
            )
            assert scalar(
                admin, "SELECT is_active FROM eta_targets WHERE id = %s", (target_id,)
            ) is False
            assert scalar(
                admin,
                "SELECT count(*) FROM notification_cancels "
                "WHERE device_id = %s AND alert_id IN (%s, %s)",
                (device_id, deleted_alert_id, deleted_eta_alert_id),
            ) == 2
    finally:
        db._pool = None
        settings.database_url = previous_url
        with connect_env("ADMIN_DATABASE_URL") as admin:
            if device_id is not None:
                admin.execute("DELETE FROM devices WHERE id = %s", (device_id,))
            if health_id is not None:
                admin.execute("DELETE FROM health_alerts WHERE id = %s", (health_id,))
            admin.execute("DELETE FROM observations WHERE checkpoint_id = %s", (checkpoint_id,))
            admin.execute("DELETE FROM checkpoints WHERE id = %s", (checkpoint_id,))
