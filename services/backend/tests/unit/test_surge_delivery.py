"""Новий push не запускає legacy fallback, TTL обмежений актуальністю."""

import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock

import pytest

from avelren import cancels, fcm, notifier, surge_delivery

T = datetime(2026, 10, 2, 10, tzinfo=UTC)


def test_payload_and_ttl_are_explicit_and_distinct():
    row = {
        "id": 1,
        "ordinal": 2,
        "created_at": T,
        "alert_id": 42,
        "attempt_id": "fixture-attempt",
        "kind": "surge_started",
        "checkpoint_id": 17,
        "title": "fixture",
        "expires_at": T + timedelta(seconds=100),
    }
    payload = surge_delivery.delivery_payload(row)
    assert payload["surge_alert_id"] == "42"
    assert payload["attempt_id"] == "fixture-attempt"
    assert payload["attempt_ordinal"] == "2"
    assert payload["attempt_created_at"] == T.isoformat()
    assert payload["body"] == "Почалось зростання черги на Чопі"
    assert payload["experimental"] == "true"
    assert "alert_id" not in payload
    assert surge_delivery.delivery_ttl(row, T) == 100
    assert surge_delivery.delivery_ttl(row, T + timedelta(seconds=101)) == 0
    assert surge_delivery.delivery_ttl({**row, "expires_at": T + timedelta(hours=1)}, T) == 360


def test_disabled_delivery_never_opens_pool(monkeypatch):
    monkeypatch.setattr(surge_delivery.settings, "surge_enabled", False)
    denied = AsyncMock(side_effect=AssertionError("DB access"))
    monkeypatch.setattr(surge_delivery, "get_pool", denied)
    assert asyncio.run(surge_delivery.send_due(object(), T)) == 0
    denied.assert_not_called()


class Pool:
    def __init__(self):
        self.exited = 0
        cursor = Mock()
        cursor.fetchall = AsyncMock(return_value=[])
        self.conn = Mock()
        self.conn.execute = AsyncMock(return_value=cursor)

    @asynccontextmanager
    async def connection(self):
        yield self.conn
        self.exited += 1


@pytest.mark.parametrize("fails", [False, True])
def test_notifier_runs_surge_after_legacy_commit_and_cancels_afterward(monkeypatch, fails):
    pool = Pool()
    monkeypatch.setattr(notifier, "get_pool", lambda: pool)

    async def surge(*args):
        assert pool.exited == 1
        if fails:
            raise RuntimeError("fixture")
        return 1

    sender = AsyncMock(side_effect=surge)
    monkeypatch.setattr(surge_delivery, "send_due", sender)
    cancels_phase = AsyncMock()
    monkeypatch.setattr(notifier, "_send_cancels", cancels_phase)
    monkeypatch.setattr(cancels, "cleanup_closed", AsyncMock())
    result = asyncio.run(notifier.run_cycle(object()))
    sender.assert_awaited_once()
    cancels_phase.assert_awaited_once()
    assert result == int(not fails)


@pytest.mark.parametrize("kind", ["surge_forecast", "surge_started"])
def test_surge_cancel_cannot_cancel_legacy_notification(kind):
    payload = fcm.cancel_payload(kind, 42)
    assert payload == {"type": "cancel", "kind": kind, "cancel_surge_alert_id": "42"}
    assert "cancel_alert_id" not in payload
    assert "alert_id" not in payload
