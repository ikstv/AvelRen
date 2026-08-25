"""Telemetry reads only the host snapshot, not /proc/secrets/run.

These tests are effectively the contract "the API container has no direct access
to host files": if someone reverts to reading /proc or /secrets directly, the
tests fail, because in CI those paths do not exist for our container, and the
fixture substitutes only the snapshot file.

Regression for audit SEC-1 / A-01.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest

from avelren import telemetry


@pytest.fixture()
def snapshot(tmp_path, monkeypatch):
    """A temporary snapshot file with controlled content and mtime."""
    path = tmp_path / "host.json"
    monkeypatch.setattr(telemetry, "SNAPSHOT_PATH", path)

    def write(payload: dict, *, collected_at: datetime | None = None) -> None:
        if collected_at is not None:
            payload = {
                **payload,
                "collected_at": collected_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        path.write_text(json.dumps(payload), encoding="utf-8")

    return write


def test_system_reads_from_snapshot(snapshot):
    snapshot(
        {
            "system": {
                "uptime_seconds": 12345,
                "load_1m": 0.42,
                "cpu_count": 4,
                "memory_total_mb": 8000,
                "memory_used_mb": 3200,
                "disk_free_gb": 21.5,
                "disk_total_gb": 40.0,
                "disk_used_percent": 46,
                "reboot_required": False,
                "reboot_pending_days": None,
            }
        },
        collected_at=datetime.now(UTC),
    )
    result = telemetry.system()
    assert result["uptime_seconds"] == 12345
    assert result["load_1m"] == 0.42
    assert result["stale"] is False


def test_system_marks_stale_when_snapshot_missing(tmp_path, monkeypatch):
    """No snapshot — not a 500, but an honest stale: the API handler must survive
    even if the host timer broke."""
    monkeypatch.setattr(telemetry, "SNAPSHOT_PATH", tmp_path / "missing.json")
    result = telemetry.system()
    assert result["stale"] is True
    assert result["snapshot_age_seconds"] is None


def test_system_marks_stale_when_snapshot_old(snapshot):
    """A snapshot older than 5 min is also stale. Otherwise stale numbers look
    fresh and hide a failure of the telemetry pipeline."""
    snapshot(
        {"system": {"cpu_count": 2}},
        collected_at=datetime.now(UTC) - timedelta(minutes=10),
    )
    result = telemetry.system()
    assert result["stale"] is True
    assert result["snapshot_age_seconds"] > telemetry.SNAPSHOT_MAX_AGE_SECONDS


def test_network_reads_from_snapshot(snapshot):
    snapshot(
        {"network": {"rx_total_gb": 12.34, "tx_total_gb": 5.67}},
        collected_at=datetime.now(UTC),
    )
    assert telemetry.network() == {"rx_total_gb": 12.34, "tx_total_gb": 5.67}


def test_network_defaults_when_snapshot_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(telemetry, "SNAPSHOT_PATH", tmp_path / "missing.json")
    assert telemetry.network() == {"rx_total_gb": 0.0, "tx_total_gb": 0.0}


def test_backups_reads_from_snapshot(snapshot):
    snapshot(
        {"backups": {"last_run": 1_700_000_000, "age_hours": 12.5, "stale": False}},
        collected_at=datetime.now(UTC),
    )
    assert telemetry.backups() == {
        "last_run": 1_700_000_000,
        "age_hours": 12.5,
        "stale": False,
    }


def test_certificate_reads_from_snapshot(snapshot):
    snapshot(
        {"certificate": {"days_left": 42, "issuer": "Let's Encrypt", "error": None}},
        collected_at=datetime.now(UTC),
    )
    result = telemetry.certificate()
    assert result["days_left"] == 42
    assert result["issuer"] == "Let's Encrypt"


def test_certificate_reports_snapshot_missing(tmp_path, monkeypatch):
    """Without a snapshot, certificate() does not do its own TLS connect (which is
    how it used to be — synchronously from an async handler). Instead — an honest message."""
    monkeypatch.setattr(telemetry, "SNAPSHOT_PATH", tmp_path / "missing.json")
    result = telemetry.certificate()
    assert result == {"error": "snapshot missing"}


def test_stale_snapshot_becomes_a_visible_problem(snapshot):
    """Regression for review PR #3: without this, a broken timer looked on the
    phone like a healthy server — fields became zeros, and the app wrote "No
    problems". Android has `ignoreUnknownKeys`, so it simply discarded the new
    `stale` field; the only way to convey this without changing the client is the
    `problems` list."""
    snapshot(
        {"system": {"cpu_count": 2}},
        collected_at=datetime.now(UTC) - timedelta(minutes=17),
    )
    problem = telemetry.snapshot_problem(telemetry.system())
    assert problem is not None
    assert problem["kind"] == "telemetry_snapshot_stale"
    # The shape matches the health_alerts rows — the client renders it as a regular one.
    assert set(problem) == {"kind", "detail", "first_seen", "send_count"}
    assert "17" in problem["detail"]


def test_missing_snapshot_becomes_a_visible_problem(tmp_path, monkeypatch):
    monkeypatch.setattr(telemetry, "SNAPSHOT_PATH", tmp_path / "missing.json")
    problem = telemetry.snapshot_problem(telemetry.system())
    assert problem is not None
    assert problem["kind"] == "telemetry_snapshot_stale"
    assert "absent" in problem["detail"]


def test_fresh_snapshot_produces_no_problem(snapshot):
    """A healthy timer must not clutter the problem list."""
    snapshot({"system": {"cpu_count": 2}}, collected_at=datetime.now(UTC))
    assert telemetry.snapshot_problem(telemetry.system()) is None


def test_admin_telemetry_surfaces_stale_snapshot(device, api_client, conn, monkeypatch, tmp_path):
    """End-to-end: /admin/telemetry must return stale as a problem, not stay silent."""
    conn.execute("UPDATE devices SET is_admin = true WHERE id = %s", (device.device_id,))
    monkeypatch.setattr(telemetry, "SNAPSHOT_PATH", tmp_path / "missing.json")

    r = api_client.get("/admin/telemetry", headers=device.headers())
    assert r.status_code == 200
    body = r.json()
    assert body["system"]["stale"] is True
    kinds = [p["kind"] for p in body["problems"]]
    assert "telemetry_snapshot_stale" in kinds


def test_snapshot_survives_partial_json(tmp_path, monkeypatch):
    """Corrupt JSON must not crash the API. The reader sees "snapshot absent"."""
    path = tmp_path / "host.json"
    path.write_text("{ not valid json", encoding="utf-8")
    monkeypatch.setattr(telemetry, "SNAPSHOT_PATH", path)
    assert telemetry.system()["stale"] is True
    assert telemetry.network() == {"rx_total_gb": 0.0, "tx_total_gb": 0.0}


# /health carries the reboot signal publicly (no auth) so every client — not only
# admins — can show a truthful "server is updating" badge instead of guessing from
# data staleness. The full telemetry stays admin-only; /health exposes only the
# safe boolean + day count.
def test_health_exposes_reboot_required(api_client, snapshot):
    snapshot(
        {"system": {"reboot_required": True, "reboot_pending_days": 2}},
        collected_at=datetime.now(UTC),
    )
    r = api_client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["reboot_required"] is True
    assert body["reboot_pending_days"] == 2


def test_health_reboot_required_defaults_false_without_flag(api_client, snapshot):
    snapshot({"system": {}}, collected_at=datetime.now(UTC))
    body = api_client.get("/health").json()
    assert body["reboot_required"] is False
    assert body["reboot_pending_days"] is None


def test_health_reboot_required_false_when_snapshot_absent(api_client, monkeypatch, tmp_path):
    # A missing/stale snapshot must never light the "restarting" badge: absent
    # signal is not "restarting", it is "unknown" → false.
    monkeypatch.setattr(telemetry, "SNAPSHOT_PATH", tmp_path / "missing.json")
    body = api_client.get("/health").json()
    assert body["reboot_required"] is False
