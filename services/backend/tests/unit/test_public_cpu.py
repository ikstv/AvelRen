"""Публічний CPU: вузька відповідь без БД, probe чи приватної телеметрії."""

import json
import subprocess
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from avelren import api, telemetry

NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)


@pytest.fixture
def public_cpu(tmp_path, monkeypatch):
    path = tmp_path / "host.json"
    monkeypatch.setattr(telemetry, "SNAPSHOT_PATH", path)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)

    monkeypatch.setattr(api, "datetime", Clock)

    def forbidden(*args, **kwargs):
        raise AssertionError("Public CPU must not query DB or run host probes")

    monkeypatch.setattr(api, "get_pool", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)

    def request(snapshot, raw=None):
        if raw is not None:
            path.write_text(raw, encoding="utf-8")
        elif snapshot is not None:
            path.write_text(json.dumps(snapshot), encoding="utf-8")
        response = TestClient(api.app).get("/server/status")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        payload = response.json()
        assert set(payload) == {"cpu_percent", "measured_at", "sample_seconds", "stale",
                               "memory", "disk", "traffic"}
        assert all(payload[name]["stale"] for name in ("memory", "disk", "traffic"))
        return {name: payload[name] for name in ("cpu_percent", "measured_at", "sample_seconds", "stale")}

    return request


def snapshot(cpu=0, stamp="2026-10-07T11:59:00Z", sample=1):
    return {"system": {"cpu_percent": cpu, "cpu_measured_at": stamp,
                       "cpu_sample_seconds": sample, "private": "do not expose"},
            "secrets": {"token": "synthetic-not-a-secret"}, "devices": 123}


@pytest.mark.parametrize("cpu", [0, 50.0, 100])
def test_public_cpu_keeps_valid_percent_and_only_allowed_fields(public_cpu, cpu):
    assert public_cpu(snapshot(cpu)) == {"cpu_percent": cpu,
        "measured_at": "2026-10-07T11:59:00Z", "sample_seconds": 1, "stale": False}


@pytest.mark.parametrize("stamp,fresh", [
    ("2026-10-07T11:55:00Z", True),
    ("2026-10-07T11:54:59Z", False),
    ("2026-10-07T12:00:01Z", False),
    ("2026-10-07T11:59:00", False),
    ("invalid", False), (None, False), (123, False),
])
def test_public_cpu_freshness_boundaries(public_cpu, stamp, fresh):
    result = public_cpu(snapshot(37, stamp))
    assert result["stale"] is not fresh
    assert result["cpu_percent"] == (37 if fresh else None)


@pytest.mark.parametrize("cpu", [True, False, float("nan"), float("inf"), -1, 101,
                                10**400, "50", None])
def test_invalid_cpu_never_looks_like_zero(public_cpu, cpu):
    result = public_cpu(snapshot(cpu))
    assert result["cpu_percent"] is None
    assert result["stale"] is True


@pytest.mark.parametrize("data", [None, [], "wrong", {}, {"system": []}, {"system": None}])
def test_unavailable_snapshot_is_safe(public_cpu, data):
    assert public_cpu(data) == {"cpu_percent": None, "measured_at": None,
                               "sample_seconds": None, "stale": True}


@pytest.mark.parametrize("sample", [None, True, 0, 2, "1"])
def test_invalid_sample_window_is_not_trusted(public_cpu, sample):
    result = public_cpu(snapshot(37, sample=sample))
    assert result["cpu_percent"] is None
    assert result["sample_seconds"] is None
    assert result["stale"] is True


@pytest.mark.parametrize("stamp", ["0001-01-01T00:00:00+01:00",
                                  "9999-12-31T23:59:59-01:00"])
def test_timestamp_outside_utc_range_is_unavailable(public_cpu, stamp):
    assert public_cpu(snapshot(37, stamp)) == {
        "cpu_percent": None, "measured_at": None, "sample_seconds": None, "stale": True}


def test_oversized_json_integer_is_unavailable(public_cpu):
    assert public_cpu(None, raw='{"system":{"cpu_percent":' + '1' * 4301 + '}}') == {
        "cpu_percent": None, "measured_at": None, "sample_seconds": None, "stale": True}
