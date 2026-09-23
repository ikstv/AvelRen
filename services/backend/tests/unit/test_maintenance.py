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
    monkeypatch.setattr(maintenance, "MAINTENANCE_PATH", path)
    return path


@pytest.mark.parametrize("offset,duration,valid", [(0, 180, True), (120, 180, True),
    (-30, 180, True), (-180, 180, False), (86401, 180, False), (0, 901, False), (0, 0, False)])
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
