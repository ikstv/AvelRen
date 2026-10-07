"""Ресурс не може виглядати свіжим нулем за відсутніх або хибних даних."""
from datetime import UTC, datetime

import pytest

from avelren import public_resources

NOW = datetime(2026, 10, 7, 12, tzinfo=UTC)


@pytest.mark.parametrize("used,total", [(0, 100), (100, 100), (40, 100)])
def test_valid_resource_preserves_exact_bytes(used, total):
    assert public_resources.resource_status(used, total, "2026-10-07T12:00:00Z", NOW, 300) == {
        "used_bytes": used, "total_bytes": total,
        "measured_at": "2026-10-07T12:00:00Z", "stale": False,
    }


@pytest.mark.parametrize("used,total", [
    (True, 100), (0, False), (-1, 100), (0, 0), (101, 100),
    (None, 100), (1.5, 100), (0, 2**63), (float("nan"), 100),
])
def test_invalid_bytes_are_unavailable(used, total):
    result = public_resources.resource_status(used, total, "2026-10-07T12:00:00Z", NOW, 300)
    assert result["stale"] is True
    assert result["used_bytes"] is None
    assert result["total_bytes"] is None


@pytest.mark.parametrize("stamp,fresh", [
    ("2026-10-07T11:55:00Z", True), ("2026-10-07T11:54:59Z", False),
    ("2026-10-07T12:00:01Z", False), ("2026-10-07T12:00:00", False),
    (None, False), ("bad", False), ("0001-01-01T00:00:00+01:00", False),
])
def test_resource_ages_independently(stamp, fresh):
    result = public_resources.resource_status(40, 100, stamp, NOW, 300)
    assert result["stale"] is not fresh
    assert result["used_bytes"] == (40 if fresh else None)


def test_traffic_overage_is_not_lost():
    result = public_resources.resource_status(110, 100, "2026-10-07T10:00:00Z", NOW, 7200, True)
    assert result["used_bytes"] == 110
    assert result["stale"] is False


def test_public_resources_whitelist_and_partial_old_snapshot(monkeypatch):
    from avelren import telemetry

    monkeypatch.setattr(telemetry, "_snapshot", lambda: {
        "system": {"memory_used_bytes": 40, "memory_total_bytes": 100,
                   "secret": "private"}, "collected_at": "2026-10-07T12:00:00Z",
        "network": {"tx_total_gb": 999},
    })
    result = telemetry.public_resource_status(NOW)
    assert set(result) == {"cpu_percent", "measured_at", "sample_seconds", "stale",
                           "memory", "disk", "traffic"}
    assert result["memory"]["used_bytes"] == 40
    assert result["disk"]["stale"] is True
    assert result["traffic"]["used_bytes"] is None
    assert "private" not in str(result)


def test_oversized_host_snapshot_is_unavailable(tmp_path, monkeypatch):
    from avelren import telemetry

    path = tmp_path / "host.json"
    path.write_text('{"padding":"' + 'x' * 1048576 + '"}', encoding="utf-8")
    monkeypatch.setattr(telemetry, "SNAPSHOT_PATH", path)
    assert telemetry._snapshot() == {}
