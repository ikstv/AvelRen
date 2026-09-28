"""Вікно робіт обмежене часом; публічна відповідь не містить телеметрії."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from avelren import maintenance
from avelren.api import app


@pytest.fixture
def window(tmp_path, monkeypatch):
    path = tmp_path / "maintenance.json"
    boot_id = tmp_path / "boot_id"
    boot_id.write_text("boot-before-restart\n", encoding="utf-8")
    monkeypatch.setattr(maintenance, "MAINTENANCE_PATH", path)
    monkeypatch.setattr(maintenance, "BOOT_ID_PATH", boot_id)
    return path


@pytest.mark.parametrize("offset,duration,valid", [(0, 180, True), (120, 180, True),
    (-30, 180, True), (-180, 180, False), (86401, 180, False),
    (0, 21600, True), (0, 21601, False), (0, 0, False)])
def test_bounded_window(window, offset, duration, valid):
    now = datetime(2026, 9, 22, 12, tzinfo=UTC)
    start = now + timedelta(seconds=offset)
    window.write_text(json.dumps({
        "starts_at": start.isoformat(),
        "ends_at": (start + timedelta(seconds=duration)).isoformat(),
        "private": "not public",
    }), encoding="utf-8")
    result = maintenance.read_window(now)
    assert (result is not None) == valid
    if result:
        assert set(result) == {"starts_at", "ends_at"}


@pytest.mark.parametrize("duration", [901, 21600])
def test_restart_window_keeps_short_limit(window, duration):
    now = datetime(2026, 9, 27, 12, tzinfo=UTC)
    window.write_text(json.dumps({
        "starts_at": now.isoformat(),
        "restarts_at": (now + timedelta(seconds=75)).isoformat(),
        "ends_at": (now + timedelta(seconds=duration)).isoformat(),
        "boot_id": "boot-before-restart",
    }), encoding="utf-8")

    assert maintenance.read_window(now) is None


@pytest.mark.parametrize("payload", [None, [], {}, {"starts_at": False, "ends_at": 3},
    {"starts_at": "2026-09-22T12:00:00", "ends_at": "2026-09-22T12:03:00"}])
def test_invalid_window_is_not_maintenance(window, payload):
    window.write_text(json.dumps(payload), encoding="utf-8")
    assert maintenance.read_window(datetime.now(UTC)) is None


def test_missing_file_is_not_maintenance(window):
    assert maintenance.read_window(datetime.now(UTC)) is None


def test_public_endpoint_is_read_only_and_no_store(window):
    now = datetime.now(UTC)
    window.write_text(json.dumps({
        "starts_at": now.isoformat(), "ends_at": (now + timedelta(minutes=3)).isoformat(),
        "secret": "not public",
    }), encoding="utf-8")
    client = TestClient(app)  # Без lifespan: цей маршрут не потребує БД.
    try:
        response = client.get("/status")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert set(response.json()["maintenance"]) == {"starts_at", "ends_at"}
        assert "secret" not in response.text
        assert client.post("/status", json={}).status_code == 405
    finally:
        client.close()


def test_planned_restart_exposes_schedule_but_not_boot_identity(window):
    now = datetime(2026, 9, 27, 12, tzinfo=UTC)
    window.write_text(json.dumps({
        "starts_at": now.isoformat(),
        "restarts_at": (now + timedelta(seconds=75)).isoformat(),
        "ends_at": (now + timedelta(minutes=10)).isoformat(),
        "boot_id": "boot-before-restart",
    }), encoding="utf-8")

    result = maintenance.read_window(now)

    assert result == {
        "starts_at": now.isoformat(),
        "restarts_at": (now + timedelta(seconds=75)).isoformat(),
        "ends_at": (now + timedelta(minutes=10)).isoformat(),
    }


def test_completed_restart_clears_window_from_public_status(window, tmp_path):
    now = datetime(2026, 9, 27, 12, tzinfo=UTC)
    window.write_text(json.dumps({
        "starts_at": now.isoformat(),
        "restarts_at": (now + timedelta(seconds=75)).isoformat(),
        "ends_at": (now + timedelta(minutes=10)).isoformat(),
        "boot_id": "boot-before-restart",
    }), encoding="utf-8")
    maintenance.BOOT_ID_PATH.write_text("boot-after-restart\n", encoding="utf-8")

    assert maintenance.read_window(now + timedelta(seconds=100)) is None


def test_planned_restart_is_hidden_when_api_cannot_read_boot_identity(window):
    now = datetime(2026, 9, 27, 12, tzinfo=UTC)
    window.write_text(json.dumps({
        "starts_at": now.isoformat(),
        "restarts_at": (now + timedelta(seconds=90)).isoformat(),
        "ends_at": (now + timedelta(minutes=10)).isoformat(),
        "boot_id": "boot-before-restart",
    }), encoding="utf-8")
    maintenance.BOOT_ID_PATH.unlink()

    assert maintenance.read_window(now) is None


@pytest.mark.parametrize("restart_offset", [-1, 0, 600, 601])
def test_restart_must_be_strictly_inside_window(window, restart_offset):
    now = datetime(2026, 9, 27, 12, tzinfo=UTC)
    window.write_text(json.dumps({
        "starts_at": now.isoformat(),
        "restarts_at": (now + timedelta(seconds=restart_offset)).isoformat(),
        "ends_at": (now + timedelta(seconds=600)).isoformat(),
        "boot_id": "boot-before-restart",
    }), encoding="utf-8")

    assert maintenance.read_window(now) is None
