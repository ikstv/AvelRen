"""Стійкі спроби до FCM, callback/ACK гонка та нове нагадування."""

from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from psycopg.rows import dict_row

from avelren import surge_delivery

T = datetime(2026, 10, 2, 10, tzinfo=UTC)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def alert(database):
    with psycopg.connect(database("admin")) as c:
        c.execute("INSERT INTO checkpoints(id,title,for_vehicle_type) VALUES(17,'fixture',1)")
        device = c.execute(

                "INSERT INTO devices(fcm_token,notification_capabilities) "
                "VALUES('synthetic-token',ARRAY['surge_v1']) RETURNING id"

        ).fetchone()[0]
        event = c.execute(
            (
                "INSERT INTO surge_events(checkpoint_id,kind,started_at,"
                "updated_at,expires_at) VALUES(17,'surge_started',%s,%s,%s) "
                "RETURNING id"
            ),
            (T, T, T + timedelta(minutes=30)),
        ).fetchone()[0]
        return c.execute(
            (
                "INSERT INTO surge_alerts(event_id,device_id,next_attempt_at) "
                "VALUES(%s,%s,%s) RETURNING id"
            ),
            (event, device, T),
        ).fetchone()[0]


async def reserve(database, alert, now):
    async with await psycopg.AsyncConnection.connect(
        database("notifier"), autocommit=True, row_factory=dict_row
    ) as c:
        return await surge_delivery.reserve_attempt(c, alert, now)


@pytest.mark.anyio
async def test_reservation_commits_before_send_and_timeout_reuses_id(database, alert):
    first = await reserve(database, alert, T)
    with psycopg.connect(database("admin")) as c:
        assert (
            c.execute("SELECT attempt_id FROM surge_delivery_attempts").fetchone()[0]
            == first["attempt_id"]
        )
    assert await reserve(database, alert, T + timedelta(seconds=30)) is None
    retry = await reserve(database, alert, T + timedelta(seconds=60))
    assert retry["attempt_id"] == first["attempt_id"]
    assert retry["ordinal"] == 1


@pytest.mark.anyio
async def test_new_ordinal_after_accepted_reminder(database, alert):
    first = await reserve(database, alert, T)
    async with await psycopg.AsyncConnection.connect(database("notifier"), autocommit=True) as c:
        await surge_delivery.accept_attempt(c, first, T + timedelta(seconds=60))
    assert await reserve(database, alert, T + timedelta(seconds=359)) is None
    second = await reserve(database, alert, T + timedelta(seconds=360))
    assert second["ordinal"] == 2
    assert second["attempt_id"] != first["attempt_id"]


@pytest.mark.anyio
async def test_unknown_response_still_gets_new_scheduled_reminder(database, alert):
    first = await reserve(database, alert, T)
    second = await reserve(database, alert, T + timedelta(seconds=300))
    assert second["ordinal"] == 2
    assert second["attempt_id"] != first["attempt_id"]
    with psycopg.connect(database("admin")) as c:
        old = c.execute(
            "SELECT accepted_at,abandoned_at FROM surge_delivery_attempts WHERE attempt_id=%s",
            (first["attempt_id"],),
        ).fetchone()
        assert old[0] is None and old[1] is not None


@pytest.mark.anyio
@pytest.mark.parametrize("status", ["acknowledged", "expired"])
async def test_ack_or_expiry_never_reserves(database, alert, status):
    with psycopg.connect(database("admin")) as c:
        c.execute("UPDATE surge_alerts SET status=%s WHERE id=%s", (status, alert))
    assert await reserve(database, alert, T) is None


@pytest.mark.anyio
async def test_callback_after_ack_requeues_cancel_without_rearming(database, alert):
    first = await reserve(database, alert, T)
    with psycopg.connect(database("admin")) as c:
        c.execute(
            "UPDATE surge_alerts SET status='acknowledged',acknowledged_at=%s WHERE id=%s",
            (T, alert),
        )
        c.execute(
            (
                "INSERT INTO notification_cancels(kind,alert_id,device_id,"
                "accepted_at) SELECT 'surge_started',id,device_id,%s FROM "
                "surge_alerts WHERE id=%s"
            ),
            (T, alert),
        )
    async with await psycopg.AsyncConnection.connect(database("notifier"), autocommit=True) as c:
        await surge_delivery.accept_attempt(c, first, T + timedelta(seconds=1))
    with psycopg.connect(database("admin")) as c:
        assert c.execute("SELECT status FROM surge_alerts WHERE id=%s", (alert,)).fetchone() == (
            "acknowledged",
        )
        assert c.execute(
            "SELECT accepted_at FROM notification_cancels WHERE alert_id=%s", (alert,)
        ).fetchone() == (None,)
    assert await reserve(database, alert, T + timedelta(seconds=360)) is None


@pytest.mark.anyio
async def test_real_sender_reserves_before_http_and_retries_same_payload(
    database, alert, monkeypatch
):
    import httpx

    from avelren import db, fcm
    from avelren.config import settings

    clock = [T]
    monkeypatch.setattr(settings, "database_url", database("notifier"))
    monkeypatch.setattr(settings, "surge_enabled", True)
    monkeypatch.setattr(db, "_pool", None)
    monkeypatch.setattr(surge_delivery, "utc_now", lambda: clock[0])
    sent = []

    async def fake_send(client, token, payload, **kwargs):
        with psycopg.connect(database("admin")) as c:
            assert (
                c.execute("SELECT attempt_id FROM surge_delivery_attempts").fetchone() is not None
            )
        assert kwargs["ttl_seconds"] <= 360
        assert kwargs["collapse_key"] == f"surge_started:{alert}"
        sent.append(payload)
        if len(sent) == 1:
            raise httpx.ReadTimeout("fixture")

    monkeypatch.setattr(fcm, "send", fake_send)
    pool = db.get_pool()
    await pool.open()
    try:
        assert await surge_delivery.send_due(object(), T) == 0
        clock[0] = T + timedelta(seconds=60)
        assert await surge_delivery.send_due(object(), clock[0]) == 1
        assert sent[0]["attempt_id"] == sent[1]["attempt_id"]
        with psycopg.connect(database("admin")) as c:
            assert c.execute("SELECT accepted_at FROM surge_delivery_attempts").fetchone() == (
                clock[0],
            )
    finally:
        await pool.close()
        db._pool = None


@pytest.mark.anyio
async def test_dead_token_only_clears_matching_current_token(database, alert, monkeypatch):
    from avelren import db, fcm
    from avelren.config import settings

    monkeypatch.setattr(settings, "database_url", database("notifier"))
    monkeypatch.setattr(settings, "surge_enabled", True)
    monkeypatch.setattr(db, "_pool", None)
    monkeypatch.setattr(surge_delivery, "utc_now", lambda: T)

    async def dead(*args, **kwargs):
        raise fcm.FcmError(
            http_status=404,
            canonical_status="NOT_FOUND",
            fcm_error_code="UNREGISTERED",
            message="fixture",
            dead_token=True,
            retryable=False,
        )

    monkeypatch.setattr(fcm, "send", dead)
    pool = db.get_pool()
    await pool.open()
    try:
        assert await surge_delivery.send_due(object(), T) == 0
        with psycopg.connect(database("admin")) as c:
            assert c.execute("SELECT fcm_token FROM devices").fetchone() == (None,)
            assert c.execute("SELECT abandoned_at FROM surge_delivery_attempts").fetchone() == (T,)
    finally:
        await pool.close()
        db._pool = None
