"""Контракт нової схеми, optional gate та обмеженої ролі."""

import psycopg
import pytest

from avelren.schema_gate import SchemaTooOldError, assert_surge_schema, required_schema_version


@pytest.fixture
def anyio_backend():
    return "asyncio"


TABLES = (
    "surge_subscriptions",
    "surge_predictions",
    "surge_events",
    "surge_alerts",
    "surge_delivery_attempts",
    "surge_checkpoint_state",
)


@pytest.mark.anyio
@pytest.mark.parametrize("database", [15], indirect=True)
async def test_optional_schema_does_not_raise_legacy_minimum(database):
    assert required_schema_version() == "015_wait_time_status"
    async with await psycopg.AsyncConnection.connect(database("api")) as conn:
        with pytest.raises(SchemaTooOldError, match="016"):
            await assert_surge_schema(conn)


@pytest.mark.anyio
async def test_gate_proves_objects_not_only_stamp(database):
    async with await psycopg.AsyncConnection.connect(database("api")) as conn:
        await assert_surge_schema(conn)
    with psycopg.connect(database("admin")) as conn:
        conn.execute("DROP INDEX surge_events_one_active")
    async with await psycopg.AsyncConnection.connect(database("api")) as conn:
        with pytest.raises(SchemaTooOldError):
            await assert_surge_schema(conn)


def seed(conn):
    conn.execute("INSERT INTO checkpoints(id,title,for_vehicle_type) VALUES(123,'fixture',1)")
    return conn.execute("INSERT INTO devices DEFAULT VALUES RETURNING id").fetchone()[0]


def test_subscriptions_events_attempts_and_cancels(database):
    with psycopg.connect(database("admin"), autocommit=True) as c:
        device = seed(c)
        c.execute(
            "INSERT INTO surge_subscriptions(device_id,checkpoint_id) VALUES(%s,123)", (device,)
        )
        with pytest.raises(psycopg.errors.UniqueViolation):
            c.execute(
                "INSERT INTO surge_subscriptions(device_id,checkpoint_id) VALUES(%s,123)", (device,)
            )
        event = c.execute(
            "INSERT INTO "
            "surge_events(checkpoint_id,kind,started_at,updated_at,expires_at) "
            "VALUES(123,'surge_started',now(),now(),now()+interval '30 minutes') "
            "RETURNING id"
        ).fetchone()[0]
        with pytest.raises(psycopg.errors.UniqueViolation):
            c.execute(
                "INSERT INTO "
                "surge_events(checkpoint_id,kind,started_at,updated_at,expires_at) "
                "VALUES(123,'surge_started',now(),now(),now()+interval '30 minutes')"
            )
        alert = c.execute(
            (
                "INSERT INTO surge_alerts(event_id,device_id,next_attempt_at) "
                "VALUES(%s,%s,now()) RETURNING id"
            ),
            (event, device),
        ).fetchone()[0]
        c.execute("INSERT INTO surge_delivery_attempts(alert_id,ordinal) VALUES(%s,1)", (alert,))
        with pytest.raises(psycopg.errors.UniqueViolation):
            c.execute(
                "INSERT INTO surge_delivery_attempts(alert_id,ordinal) VALUES(%s,1)", (alert,)
            )
        for statement in [
            "UPDATE surge_alerts SET status='wrong'",
            "UPDATE surge_delivery_attempts SET ordinal=0",
            "UPDATE surge_events SET expires_at=started_at-interval '1 second'",
            "UPDATE surge_events SET kind='eta'",
        ]:
            with pytest.raises(psycopg.errors.CheckViolation):
                c.execute(statement)
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            c.execute(
                "INSERT INTO surge_subscriptions(device_id,checkpoint_id) VALUES(%s,99999)",
                (device,),
            )
        for kind in ("surge_forecast", "surge_started"):
            c.execute(
                "INSERT INTO notification_cancels(kind,alert_id,device_id) VALUES(%s,%s,%s)",
                (kind, alert, device),
            )
        c.execute("DELETE FROM devices WHERE id=%s", (device,))
        assert c.execute("SELECT count(*) FROM surge_alerts").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM surge_delivery_attempts").fetchone()[0] == 0


def test_predictions_unique_and_score_bounds(database):
    with psycopg.connect(database("admin"), autocommit=True) as c:
        seed(c)
        sql = (
            "INSERT INTO "
            "surge_predictions(checkpoint_id,issued_at,window_start,window_end,"
            "model_version,score) "
            "VALUES(123,'2026-10-02T10:00Z','2026-10-02T11:00Z','2026-10-03T10:00Z','v1',%s)"
        )
        c.execute(sql, (0.9,))
        with pytest.raises(psycopg.errors.UniqueViolation):
            c.execute(sql, (0.9,))
        for value in (-0.01, 1.01, float("nan")):
            with pytest.raises(psycopg.errors.CheckViolation):
                c.execute("UPDATE surge_predictions SET score=%s", (value,))
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute("UPDATE surge_predictions SET score=NULL, reason=NULL")


def test_worker_and_backup_privileges(database):
    with psycopg.connect(database("admin"), autocommit=True) as c:
        device = seed(c)
        c.execute("SET ROLE avelren_surge")
        for table in (
            "surge_subscriptions",
            "surge_predictions",
            "surge_events",
            "surge_alerts",
            "surge_checkpoint_state",
            "observations",
            "checkpoints",
            "schema_migrations",
        ):
            c.execute(f"SELECT * FROM {table} LIMIT 0")
        c.execute("INSERT INTO surge_checkpoint_state(checkpoint_id) VALUES(123)")
        c.execute(
            (
                "INSERT INTO notification_cancels(kind,alert_id,device_id) "
                "VALUES('surge_started',1,%s)"
            ),
            (device,),
        )
        for statement in (
            "CREATE TABLE unauthorized(id int)",
            "SELECT secret_hash FROM devices LIMIT 0",
            "UPDATE observations SET vehicles_in_queue=0 WHERE false",
            "DELETE FROM surge_subscriptions WHERE false",
            "UPDATE devices SET is_admin=true WHERE false",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                c.execute(statement)
        c.execute("RESET ROLE")
        row = c.execute(
            "SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls FROM pg_roles "
            "WHERE rolname='avelren_surge'"
        ).fetchone()
        assert row == (False, False, False, False)
    with psycopg.connect(database("backup"), autocommit=True) as c:
        for table in TABLES:
            c.execute(f"SELECT * FROM {table} LIMIT 0")
        for table in TABLES[:-1]:
            c.execute(f"SELECT * FROM {table}_id_seq")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("DELETE FROM surge_events WHERE false")


def test_alert_identity_does_not_rewind_with_restored_sequence(database):
    import psycopg

    with psycopg.connect(database("admin")) as c:
        c.execute("INSERT INTO checkpoints(id,title,for_vehicle_type) VALUES(17,'fixture',1)")
        device = c.execute("INSERT INTO devices DEFAULT VALUES RETURNING id").fetchone()[0]
        event = c.execute(
            "INSERT INTO surge_events(checkpoint_id,kind,started_at,updated_at,expires_at) "
            "VALUES(17,'surge_started',now(),now(),now()+interval '1 hour') RETURNING id"
        ).fetchone()[0]
        first = c.execute(
            "INSERT INTO surge_alerts(event_id,device_id,next_attempt_at) "
            "VALUES(%s,%s,now()) RETURNING id",
            (event, device),
        ).fetchone()[0]
        c.execute("DELETE FROM surge_alerts WHERE id=%s", (first,))
        # Модель restore: попередню доставлену подію втрачено, sequence повернулась.
        c.execute("SELECT setval('surge_alerts_id_seq',%s,false)", (first,))
        second = c.execute(
            "INSERT INTO surge_alerts(event_id,device_id,next_attempt_at) "
            "VALUES(%s,%s,now()) RETURNING id",
            (event, device),
        ).fetchone()[0]
        assert second != first
        assert 0 < second < 2**63
