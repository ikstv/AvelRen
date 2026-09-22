"""Щоденний звіт на повній БД під роллю watchdog; FCM завжди підмінений."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from avelren import fcm, watchdog
from avelren.schema_gate import assert_schema_at_least


@pytest.fixture
def report(database, monkeypatch):
    state = {"now": datetime(2026, 9, 22, 11, tzinfo=watchdog.KYIV)}

    class Clock:
        @staticmethod
        def now(tz):
            return state["now"].astimezone(tz)

    monkeypatch.setattr(watchdog, "datetime", Clock)
    monkeypatch.setattr(
        watchdog,
        "_read_snapshot",
        lambda: {
            "script_sha256": watchdog.EXPECTED_SNAPSHOT_SHA,
            "system": {"reboot_required": False},
            "backups": {"age_hours": 1},
            "docker": {"migrate_pin_active": True},
        },
    )
    send = AsyncMock()
    monkeypatch.setattr(fcm, "send", send)
    with psycopg.connect(database("admin"), autocommit=True, row_factory=dict_row) as admin:
        owner = admin.execute(
            "INSERT INTO devices(fcm_token,is_admin) VALUES ('synthetic-admin',true) RETURNING id"
        ).fetchone()["id"]
        admin.execute("INSERT INTO devices(fcm_token) VALUES ('synthetic-user')")

        async def run():
            async with AsyncConnectionPool(
                database("watchdog"), open=False, kwargs={"row_factory": dict_row}
            ) as pool:
                monkeypatch.setattr(watchdog, "get_pool", lambda: pool)
                await assert_schema_at_least(pool)
                await watchdog.run_cycle(object())

        yield state, send, admin, owner, lambda: asyncio.run(run())


def test_daily_only_and_restart_deduplication(report):
    state, send, admin, owner, run = report
    run()
    send.assert_not_awaited()
    assert admin.execute("SELECT kind FROM health_alerts").fetchone()["kind"] == "no_data"
    admin.execute(
        "INSERT INTO checkpoints(id,title,for_vehicle_type) VALUES (900000001,'synthetic',1)"
    )
    admin.execute("INSERT INTO observations VALUES (%s,900000001,3600,80,false)", (state["now"],))
    run()
    send.assert_not_awaited()
    assert (
        admin.execute("SELECT resolved_at FROM health_alerts WHERE kind='no_data'").fetchone()[
            "resolved_at"
        ]
        is not None
    )
    state["now"] = state["now"].replace(hour=12)
    run()
    run()  # Новий пул і цикл, журнал попереднього відправлення зберігся.
    send.assert_awaited_once()
    assert send.await_args.args[1] == "synthetic-admin"
    payload = send.await_args.args[2]
    assert payload["title"] == "AvelRen: щоденний звіт"
    assert send.await_args.kwargs["collapse_key"] == "health:daily:2026-09-22"
    assert send.await_args.kwargs["ttl_seconds"] == 1800
    rows = admin.execute(
        "SELECT kind,send_count,resolved_at FROM health_alerts WHERE kind LIKE 'daily_status:%'"
    ).fetchall()
    assert len(rows) == 1 and rows[0]["send_count"] == 1
    assert rows[0]["resolved_at"] is not None
    state["now"] += timedelta(days=1)
    run()
    assert send.await_count == 2
    assert (
        admin.execute(
            "SELECT count(*) AS n FROM health_alerts WHERE kind LIKE 'daily_status:%'"
        ).fetchone()["n"]
        == 2
    )


@pytest.mark.parametrize("dead", [False, True])
def test_fcm_failure_not_recorded_as_delivery(report, dead):
    state, send, admin, owner, run = report
    state["now"] = state["now"].replace(hour=12)
    send.side_effect = fcm.FcmError(
        http_status=404 if dead else 503,
        canonical_status="NOT_FOUND" if dead else "UNAVAILABLE",
        fcm_error_code="UNREGISTERED" if dead else "UNAVAILABLE",
        message="synthetic",
        dead_token=dead,
        retryable=not dead,
    )
    run()
    assert (
        admin.execute(
            "SELECT count(*) AS n FROM health_alerts WHERE kind LIKE 'daily_status:%'"
        ).fetchone()["n"]
        == 0
    )
    token = admin.execute("SELECT fcm_token FROM devices WHERE id=%s", (owner,)).fetchone()
    assert token["fcm_token"] == (None if dead else "synthetic-admin")
    if dead:
        run()
        send.assert_awaited_once()
        admin.execute("UPDATE devices SET fcm_token='synthetic-new-admin' WHERE id=%s", (owner,))
    send.side_effect = None
    run()
    assert (
        admin.execute(
            "SELECT count(*) AS n FROM health_alerts WHERE kind LIKE 'daily_status:%'"
        ).fetchone()["n"]
        == 1
    )


def test_no_admin_token_keeps_report_pending(report):
    state, send, admin, owner, run = report
    state["now"] = state["now"].replace(hour=12)
    admin.execute("UPDATE devices SET fcm_token=NULL WHERE id=%s", (owner,))
    run()
    send.assert_not_awaited()
    assert (
        admin.execute(
            "SELECT count(*) AS n FROM health_alerts WHERE kind LIKE 'daily_status:%'"
        ).fetchone()["n"]
        == 0
    )
    admin.execute("UPDATE devices SET fcm_token='synthetic-new-admin' WHERE id=%s", (owner,))
    run()
    send.assert_awaited_once()


def test_health_checks_remain_active_without_immediate_push(report):
    state, send, admin, owner, run = report
    state["now"] = datetime.now(UTC).astimezone(watchdog.KYIV)
    # Звіт за сьогодні вже записаний, щоб перевіряти лише діагностику.
    admin.execute(
        "INSERT INTO health_alerts(kind,detail,resolved_at) VALUES (%s,'synthetic',now())",
        (f"daily_status:{state['now'].date().isoformat()}",),
    )
    admin.execute(
        "INSERT INTO collector_runs(time,error,derived_error) "
        "SELECT now()-n*interval '1 minute','HTTP 500','synthetic' FROM generate_series(1,10) n"
    )
    run()
    send.assert_not_awaited()
    kinds = {
        r["kind"]
        for r in admin.execute(
            "SELECT kind FROM health_alerts WHERE resolved_at IS NULL"
        ).fetchall()
    }
    assert {"no_data", "collector_errors", "derived_errors"} <= kinds
    admin.execute("DELETE FROM collector_runs")
    run()
    send.assert_not_awaited()
    row = admin.execute(
        "SELECT resolved_at,send_count FROM health_alerts WHERE kind='collector_errors'"
    ).fetchone()
    assert row["resolved_at"] is not None and row["send_count"] == 0
