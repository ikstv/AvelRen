"""#113: /health carries a separate `alert_channel` bit.

Two invariants, both from the owner's corrections:

  * `status` is LIVENESS (ok/stale) — a deploy-acceptance gate and a
    container/LB healthcheck. An empty alert channel MUST NOT lower it.
  * the alert-channel probe MUST NOT be able to break /health: if it fails,
    it degrades to "unknown" and the endpoint still returns 200 with a valid
    liveness verdict.

The bit catches "empty" (no admin device with a live FCM token), NOT "dead"
(an admin with an expired-but-present token) — the latter is #19.
"""

import asyncio
import os

import psycopg
from psycopg.rows import dict_row

from avelren import telemetry

DSN = os.environ["DATABASE_URL"]


def test_health_exposes_status_and_alert_channel(api_client) -> None:  # noqa: ANN001
    r = api_client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("ok", "stale")
    assert body["alert_channel"] in ("ok", "empty", "unknown")


def test_alert_channel_ok_when_admin_has_live_token(api_client, device, conn) -> None:  # noqa: ANN001
    conn.execute(
        "UPDATE devices SET is_admin=true, fcm_token='tok-admin' WHERE id=%s",
        (device.device_id,),
    )
    assert api_client.get("/health").json()["alert_channel"] == "ok"


def test_alert_channel_empty_ignores_admin_without_token(api_client, device, conn) -> None:  # noqa: ANN001
    # is_admin but NO token: the channel is "порожній" (empty), not "мертвий".
    conn.execute(
        "UPDATE devices SET is_admin=true, fcm_token=NULL WHERE id=%s",
        (device.device_id,),
    )
    assert api_client.get("/health").json()["alert_channel"] == "empty"


def test_status_independent_of_empty_alert_channel(api_client, device, conn) -> None:  # noqa: ANN001
    """An empty alert channel must not turn the deploy-acceptance gate red."""
    conn.execute(
        "UPDATE devices SET is_admin=true, fcm_token=NULL WHERE id=%s",
        (device.device_id,),
    )
    body = api_client.get("/health").json()
    assert body["alert_channel"] == "empty"
    assert body["status"] in ("ok", "stale")  # a valid liveness verdict, not an error


def test_alert_channel_unknown_when_probe_fails(api_client, monkeypatch) -> None:  # noqa: ANN001
    """Fail-safe: a broken alert-channel probe degrades to "unknown" and 200 —
    liveness must not depend on the devices table."""

    async def boom(conn):  # noqa: ANN001, ANN202
        raise RuntimeError("devices unreadable")

    monkeypatch.setattr("avelren.telemetry.alert_channel", boom)
    r = api_client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["alert_channel"] == "unknown"
    assert body["status"] in ("ok", "stale")  # liveness survived the probe failure


def test_pipeline_reports_admins_with_token_as_number(conn, device) -> None:  # noqa: ANN001
    """The exact count lives in admin-only telemetry (not the public bit)."""
    conn.execute(
        "UPDATE devices SET is_admin=true, fcm_token='tok-x' WHERE id=%s",
        (device.device_id,),
    )

    async def run() -> dict:
        async with await psycopg.AsyncConnection.connect(DSN, autocommit=True) as ac:
            ac.row_factory = dict_row
            return await telemetry.pipeline(ac)

    data = asyncio.run(run())
    assert isinstance(data["admins_with_token"], int)
    assert data["admins_with_token"] >= 1
