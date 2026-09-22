"""Watchdog reads backup-stamp and reboot facts from the host snapshot
(/telemetry/host.json), not from a mounted host /run (audit M-1 / T-06).

Covers the read logic after the mount was narrowed: both the happy path and the
fail-safe (missing/malformed snapshot or field → None → no false alarm)."""

import json

import avelren.watchdog as watchdog


def _snapshot(tmp_path, monkeypatch, data):
    path = tmp_path / "host.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(watchdog, "SNAPSHOT_PATH", path)


def test_backup_age_from_snapshot(tmp_path, monkeypatch):
    _snapshot(tmp_path, monkeypatch, {"backups": {"age_hours": 12.5}})
    assert watchdog._backup_age_hours() == 12.5


def test_backup_age_missing_snapshot_is_none(tmp_path, monkeypatch):
    monkeypatch.setattr(watchdog, "SNAPSHOT_PATH", tmp_path / "absent.json")
    assert watchdog._backup_age_hours() is None


def test_backup_age_null_field_is_none(tmp_path, monkeypatch):
    _snapshot(tmp_path, monkeypatch, {"backups": {"age_hours": None}})
    assert watchdog._backup_age_hours() is None


def test_backup_age_malformed_snapshot_is_none(tmp_path, monkeypatch):
    path = tmp_path / "host.json"
    path.write_text("{ not json", encoding="utf-8")
    monkeypatch.setattr(watchdog, "SNAPSHOT_PATH", path)
    assert watchdog._backup_age_hours() is None


def test_reboot_pending_from_snapshot(tmp_path, monkeypatch):
    _snapshot(
        tmp_path, monkeypatch,
        {"system": {"reboot_required": True, "reboot_pending_days": 4}},
    )
    assert watchdog._reboot_pending() == 4


def test_reboot_not_required_is_none(tmp_path, monkeypatch):
    _snapshot(
        tmp_path, monkeypatch,
        {"system": {"reboot_required": False, "reboot_pending_days": None}},
    )
    assert watchdog._reboot_pending() is None


def test_reboot_missing_snapshot_is_none(tmp_path, monkeypatch):
    monkeypatch.setattr(watchdog, "SNAPSHOT_PATH", tmp_path / "absent.json")
    assert watchdog._reboot_pending() is None


def test_daily_report_body_is_ukrainian_and_includes_host_counts():
    body = watchdog._daily_report_body(
        {
            "system": {
                "updates_pending": 4,
                "updates_upgradable": 5,
                "updates_security": 1,
                "reboot_required": True,
                "reboot_required_pkgs": ["linux-image", "libc6"],
                "journal_errors_24h": 2,
                "compose_errors_24h": 3,
            }
        }
    )

    assert body == (
        "Щоденний звіт AvelRen. "
        "Доступні оновлення: 5, безпекові: 1. "
        "Перезавантаження: так (linux-image, libc6). "
        "Помилки за 24 год: systemd 2, сервіси 3."
    )


def test_daily_report_body_handles_missing_snapshot_in_ukrainian():
    body = watchdog._daily_report_body(None)

    assert "телеметрія сервера недоступна" in body
    assert "Оновлення: невідомо" in body
    assert "Помилки за 24 год: невідомо" in body
