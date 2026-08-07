"""Telemetry читає лише host-snapshot, а не /proc/secrets/run.

Ці тести — фактично контракт «API-контейнер не має прямого доступу до host
файлів»: якщо хтось повернеться до читання /proc або /secrets напряму,
тести впадуть, бо в CI цих шляхів для нашого контейнера немає, а fixture
підмінює лише snapshot-файл.

Регресія на аудит SEC-1 / A-01.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest

from avelren import telemetry


@pytest.fixture()
def snapshot(tmp_path, monkeypatch):
    """Тимчасовий файл snapshot з керованим вмістом і mtime."""
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
    """Немає snapshot — не 500, а чесний stale: API-хендлер має вижити навіть
    якщо host-таймер зламався."""
    monkeypatch.setattr(telemetry, "SNAPSHOT_PATH", tmp_path / "missing.json")
    result = telemetry.system()
    assert result["stale"] is True
    assert result["snapshot_age_seconds"] is None


def test_system_marks_stale_when_snapshot_old(snapshot):
    """Snapshot старший за 5 хв — теж stale. Інакше протухлі числа виглядають
    як свіжі й приховують збій telemetry pipeline."""
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
    """Без snapshot certificate() не робить власний TLS-connect (раніше саме
    так — синхронно з async handler). Замість цього — чесне повідомлення."""
    monkeypatch.setattr(telemetry, "SNAPSHOT_PATH", tmp_path / "missing.json")
    result = telemetry.certificate()
    assert result == {"error": "snapshot missing"}


def test_stale_snapshot_becomes_a_visible_problem(snapshot):
    """Регресія на review PR #3: без цього зламаний timer виглядав на телефоні
    як здоровий сервер — поля ставали нулями, а застосунок писав «Проблем
    немає». Android має `ignoreUnknownKeys`, тож нове поле `stale` він просто
    викидав; єдиний спосіб донести це без зміни клієнта — список `problems`."""
    snapshot(
        {"system": {"cpu_count": 2}},
        collected_at=datetime.now(UTC) - timedelta(minutes=17),
    )
    problem = telemetry.snapshot_problem(telemetry.system())
    assert problem is not None
    assert problem["kind"] == "telemetry_snapshot_stale"
    # Форма збігається з рядками health_alerts — клієнт відмалює як звичайну.
    assert set(problem) == {"kind", "detail", "first_seen", "send_count"}
    assert "17" in problem["detail"]


def test_missing_snapshot_becomes_a_visible_problem(tmp_path, monkeypatch):
    monkeypatch.setattr(telemetry, "SNAPSHOT_PATH", tmp_path / "missing.json")
    problem = telemetry.snapshot_problem(telemetry.system())
    assert problem is not None
    assert problem["kind"] == "telemetry_snapshot_stale"
    assert "відсутній" in problem["detail"]


def test_fresh_snapshot_produces_no_problem(snapshot):
    """Здоровий timer не має засмічувати список проблем."""
    snapshot({"system": {"cpu_count": 2}}, collected_at=datetime.now(UTC))
    assert telemetry.snapshot_problem(telemetry.system()) is None


def test_admin_telemetry_surfaces_stale_snapshot(device, api_client, conn, monkeypatch, tmp_path):
    """Наскрізно: /admin/telemetry має віддати stale як проблему, а не мовчати."""
    conn.execute("UPDATE devices SET is_admin = true WHERE id = %s", (device.device_id,))
    monkeypatch.setattr(telemetry, "SNAPSHOT_PATH", tmp_path / "missing.json")

    r = api_client.get("/admin/telemetry", headers=device.headers())
    assert r.status_code == 200
    body = r.json()
    assert body["system"]["stale"] is True
    kinds = [p["kind"] for p in body["problems"]]
    assert "telemetry_snapshot_stale" in kinds


def test_snapshot_survives_partial_json(tmp_path, monkeypatch):
    """Пошкоджений JSON не має валити API. Читач бачить «snapshot відсутній»."""
    path = tmp_path / "host.json"
    path.write_text("{ not valid json", encoding="utf-8")
    monkeypatch.setattr(telemetry, "SNAPSHOT_PATH", path)
    assert telemetry.system()["stale"] is True
    assert telemetry.network() == {"rx_total_gb": 0.0, "tx_total_gb": 0.0}
