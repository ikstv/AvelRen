"""Час Києва, формат звіту й відправлення без реального FCM."""

import asyncio
import hashlib
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from avelren import watchdog


def test_snapshot_hash_matches_shipped_script():
    root = Path(__file__).resolve().parents[4]
    actual = hashlib.sha256((root / "ops/telemetry-snapshot.sh").read_bytes()).hexdigest()
    assert watchdog.EXPECTED_SNAPSHOT_SHA == actual


@pytest.mark.parametrize(
    "instant,due,date",
    [
        ("2026-07-01T08:59:59+00:00", False, "2026-07-01"),
        ("2026-07-01T09:00:00+00:00", True, "2026-07-01"),
        ("2026-01-01T09:59:59+00:00", False, "2026-01-01"),
        ("2026-01-01T10:00:00+00:00", True, "2026-01-01"),
        ("2026-07-01T20:59:59+00:00", True, "2026-07-01"),
        ("2026-07-01T21:00:00+00:00", False, "2026-07-02"),
    ],
)
def test_kyiv_schedule(monkeypatch, instant, due, date):
    class Clock:
        @staticmethod
        def now(tz):
            return datetime.fromisoformat(instant).astimezone(tz)

    sent = AsyncMock(return_value=False)
    notify = AsyncMock(return_value=True)
    record = AsyncMock()
    monkeypatch.setattr(watchdog, "datetime", Clock)
    monkeypatch.setattr(watchdog, "_daily_report_already_sent", sent)
    monkeypatch.setattr(watchdog, "_notify", notify)
    monkeypatch.setattr(watchdog, "_record_daily_report_sent", record)
    monkeypatch.setattr(watchdog, "_read_snapshot", lambda: None)
    conn, client = object(), object()
    asyncio.run(watchdog._deliver_daily_report(conn, client))
    if due:
        sent.assert_awaited_once_with(conn, date)
        notify.assert_awaited_once()
        assert notify.await_args.args[2] == "AvelRen: щоденний звіт"
        assert notify.await_args.args[-1] == f"daily:{date}"
        record.assert_awaited_once()
    else:
        sent.assert_not_awaited()
        notify.assert_not_awaited()
        record.assert_not_awaited()


@pytest.mark.parametrize("already_sent,accepted", [(True, True), (False, False)])
def test_no_duplicate_or_false_success(monkeypatch, already_sent, accepted):
    class Clock:
        @staticmethod
        def now(tz):
            return datetime(2026, 9, 22, 12, tzinfo=tz)

    notify = AsyncMock(return_value=accepted)
    record = AsyncMock()
    monkeypatch.setattr(watchdog, "datetime", Clock)
    monkeypatch.setattr(
        watchdog, "_daily_report_already_sent", AsyncMock(return_value=already_sent)
    )
    monkeypatch.setattr(watchdog, "_notify", notify)
    monkeypatch.setattr(watchdog, "_record_daily_report_sent", record)
    monkeypatch.setattr(watchdog, "_read_snapshot", lambda: None)
    asyncio.run(watchdog._deliver_daily_report(object(), object()))
    record.assert_not_awaited()
    assert notify.await_count == (0 if already_sent else 1)


def test_ukrainian_report_contains_production_fields():
    body = watchdog._daily_report_body(
        {
            "system": {
                "updates_pending": 4,
                "updates_upgradable": 5,
                "updates_security": 1,
                "updates_installed_24h": 2,
                "update_failures_24h": 1,
                "rebooted_24h": True,
                "reboot_required": True,
                "reboot_required_pkgs": ["linux-image", "libc6"],
                "journal_errors_24h": 2,
                "compose_errors_24h": 3,
                "disk_used_percent": 24,
                "memory_total_mb": 4000,
                "memory_used_mb": 1000,
            }
        }
    )
    assert body == (
        "Щоденний звіт AvelRen. Доступні оновлення: 5, безпекові: 1. "
        "Автоматично за 24 год: встановлено 2, помилок 1. "
        "Перезапуск за 24 год: так; потрібен зараз: так (linux-image, libc6). "
        "Ресурси: диск 24%, пам'ять 25% (норма). "
        "Помилки за 24 год: systemd 2, сервіси 3."
    )


@pytest.mark.parametrize(
    "disk,memory,status",
    [
        (79, 89, "норма"),
        (80, 20, "УВАГА"),
        (30, 90, "УВАГА"),
        (90, 20, "КРИТИЧНО: диск"),
    ],
)
def test_resource_thresholds(disk, memory, status):
    body = watchdog._daily_report_body(
        {
            "system": {
                "disk_used_percent": disk,
                "memory_total_mb": 100,
                "memory_used_mb": memory,
            }
        }
    )
    assert f"({status})" in body


def test_missing_snapshot_is_reported():
    body = watchdog._daily_report_body(None)
    assert "телеметрія сервера недоступна" in body
    assert "Оновлення: невідомо" in body


@pytest.mark.parametrize("hash_value,drift", [(None, True), ("wrong", True)])
def test_snapshot_drift(monkeypatch, hash_value, drift):
    monkeypatch.setattr(watchdog, "_read_snapshot", lambda: {"script_sha256": hash_value})
    assert (watchdog._snapshot_script_drift() is not None) == drift
