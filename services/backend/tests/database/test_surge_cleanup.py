"""Вузьке очищення не видаляє ACK/чинні повідомлення й не дає DELETE."""

import psycopg
import pytest

from avelren import schema_verify


def test_cleanup_never_deletes_ack_or_valid_subscription(database):
    with psycopg.connect(database("admin"), autocommit=True) as c:
        c.execute("INSERT INTO checkpoints(id,title,for_vehicle_type) VALUES(123,'fixture',1)")
        device = c.execute(
            "INSERT INTO devices(notification_capabilities) VALUES(ARRAY['surge_v1']) RETURNING id"
        ).fetchone()[0]
        c.execute(
            "INSERT INTO surge_subscriptions(device_id,checkpoint_id) VALUES(%s,123)", (device,)
        )
        event = c.execute(

                "INSERT INTO surge_events(checkpoint_id,kind,started_at,updated_at,"
                "expires_at) VALUES(123,'surge_forecast',now(),now(),now()+interval "
                "'65 minutes') RETURNING id"

        ).fetchone()[0]
        alert = c.execute(
            (
                "INSERT INTO surge_alerts(event_id,device_id,next_attempt_at) "
                "VALUES(%s,%s,now()) RETURNING id"
            ),
            (event, device),
        ).fetchone()[0]
        c.execute(
            (
                "INSERT INTO notification_cancels(kind,alert_id,device_id) "
                "VALUES('surge_forecast',%s,%s)"
            ),
            (alert, device),
        )
        c.execute("SET ROLE avelren_api")
        for status in ("pending", "acknowledged", "expired"):
            c.execute("UPDATE surge_alerts SET status=%s WHERE id=%s", (status, alert))
            assert c.execute(
                "SELECT discard_disabled_surge_alert(%s,%s)", (alert, device)
            ).fetchone() == (False,)
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("DELETE FROM surge_alerts WHERE id=%s", (alert,))
        c.execute("UPDATE surge_subscriptions SET forecast_enabled=false")
        c.execute("UPDATE surge_alerts SET status='acknowledged'")
        assert c.execute(
            "SELECT discard_disabled_surge_alert(%s,%s)", (alert, device)
        ).fetchone() == (False,)
        c.execute("UPDATE surge_alerts SET status='expired'")
        assert c.execute(
            "SELECT discard_disabled_surge_alert(%s,'00000000-0000-0000-0000-000000000000')",
            (alert,),
        ).fetchone() == (False,)
        assert c.execute(
            "SELECT discard_disabled_surge_alert(%s,%s)", (alert, device)
        ).fetchone() == (True,)
        assert c.execute(
            "SELECT discard_disabled_surge_alert(%s,%s)", (alert, device)
        ).fetchone() == (False,)


def test_cleanup_owner_is_verified_after_restore(database):
    with psycopg.connect(database("admin")) as c:
        c.execute("ALTER FUNCTION discard_disabled_surge_alert(bigint,uuid) OWNER TO avelren_admin")
        problems = schema_verify.verify_contract(c)
        assert any("surge cleanup" in p for p in problems)
