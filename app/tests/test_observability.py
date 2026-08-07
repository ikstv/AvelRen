"""Durable-видимість вторинного конвеєра і чесний recovery (OBS-1/OBS-2).

Захищаємо два інваріанти:
  * збій alerts/ETA стає видимим watchdog (а не лише рядком у лозі);
  * resolved_at ставиться одразу, коли проблема зникла, але recovery
    вважається доставленим лише по факту — інакше втрачений push мовчки
    ховав би відновлення.
"""

import asyncio
import os
from datetime import UTC, datetime, timedelta

import psycopg
from psycopg.rows import dict_row

from avelren import db, watchdog

DSN = os.environ["DATABASE_URL"]


def _run(coro_factory):
    async def wrap():
        async with await psycopg.AsyncConnection.connect(DSN, autocommit=True) as ac:
            ac.row_factory = dict_row
            return await coro_factory(ac)

    return asyncio.run(wrap())


def _add_run(conn, at: datetime, *, error=None, derived_error=None) -> None:
    conn.execute(
        "INSERT INTO collector_runs (time, error, derived_error) VALUES (%s, %s, %s)",
        (at, error, derived_error),
    )


# --- OBS-1: derived-статус --------------------------------------------------


def test_record_derived_success_and_failure(conn):
    at = datetime.now(UTC).replace(microsecond=0)
    _add_run(conn, at)

    _run(lambda ac: db.record_derived(ac, at, error=None))
    r = conn.execute(
        "SELECT derived_processed_at, derived_error FROM collector_runs WHERE time=%s", (at,)
    ).fetchone()
    assert r["derived_processed_at"] is not None
    assert r["derived_error"] is None

    _run(lambda ac: db.record_derived(ac, at, error="ETA впала"))
    r = conn.execute(
        "SELECT derived_error FROM collector_runs WHERE time=%s", (at,)
    ).fetchone()
    assert r["derived_error"] == "ETA впала"

    conn.execute("DELETE FROM collector_runs WHERE time=%s", (at,))


def test_watchdog_sees_derived_errors(conn):
    """10+ derived-помилок за півгодини → watchdog піднімає проблему, навіть
    якщо fetch і observations у нормі (саме той сценарій, який раніше був
    невидимий)."""
    base = datetime.now(UTC).replace(microsecond=0)
    times = [base - timedelta(minutes=i) for i in range(12)]
    for t in times:
        _add_run(conn, t, derived_error="boom")

    problems = _run(watchdog._checks)
    assert "derived_errors" in problems

    for t in times:
        conn.execute("DELETE FROM collector_runs WHERE time=%s", (t,))


def test_watchdog_ignores_few_derived_errors(conn):
    base = datetime.now(UTC).replace(microsecond=0)
    times = [base - timedelta(minutes=i) for i in range(3)]
    for t in times:
        _add_run(conn, t, derived_error="boom")

    problems = _run(watchdog._checks)
    assert "derived_errors" not in problems

    for t in times:
        conn.execute("DELETE FROM collector_runs WHERE time=%s", (t,))


# --- OBS-2: розділення resolved / recovery ---------------------------------


def _health_alert(conn, kind: str, *, resolved_ago_days=None) -> int:
    resolved = (
        None if resolved_ago_days is None
        else datetime.now(UTC) - timedelta(days=resolved_ago_days)
    )
    return conn.execute(
        "INSERT INTO health_alerts (kind, detail, resolved_at) VALUES (%s, 'x', %s) RETURNING id",
        (kind, resolved),
    ).fetchone()["id"]


def test_recovery_delivered_sets_notified(conn, device, monkeypatch):
    """Успішна доставка → recovery_notified_at виставлено."""
    conn.execute(
        "UPDATE devices SET is_admin=true, fcm_token='tok-admin' WHERE id=%s",
        (device.device_id,),
    )
    hid = _health_alert(conn, "collector_silent", resolved_ago_days=0)

    async def ok_send(*a, **k):
        return None

    monkeypatch.setattr("avelren.fcm.send", ok_send)
    _run(lambda ac: watchdog._deliver_recoveries(ac, client=None))

    assert conn.execute(
        "SELECT recovery_notified_at IS NOT NULL AS ok FROM health_alerts WHERE id=%s", (hid,)
    ).fetchone()["ok"] is True
    conn.execute("DELETE FROM health_alerts WHERE id=%s", (hid,))


def test_recovery_stays_pending_when_delivery_fails(conn):
    """Немає адмін-пристрою → _notify повертає False → recovery лишається
    неповідомленим (молодий), ретраїмо далі. Без OBS-2 resolved_at брехав би,
    що все закрито."""
    hid = _health_alert(conn, "db_size", resolved_ago_days=0)

    _run(lambda ac: watchdog._deliver_recoveries(ac, client=None))

    assert conn.execute(
        "SELECT recovery_notified_at FROM health_alerts WHERE id=%s", (hid,)
    ).fetchone()["recovery_notified_at"] is None
    conn.execute("DELETE FROM health_alerts WHERE id=%s", (hid,))


def test_recovery_given_up_when_old(conn):
    """Старший за RECOVERY_GIVE_UP_DAYS і досі недоставлений → здаємось, щоб
    не ретраїти вічно."""
    hid = _health_alert(conn, "reboot_required", resolved_ago_days=2)

    _run(lambda ac: watchdog._deliver_recoveries(ac, client=None))

    assert conn.execute(
        "SELECT recovery_notified_at IS NOT NULL AS ok FROM health_alerts WHERE id=%s", (hid,)
    ).fetchone()["ok"] is True
    conn.execute("DELETE FROM health_alerts WHERE id=%s", (hid,))
