from datetime import UTC, datetime, timedelta

from avelren import maintenance


def _write(path, payload: str) -> None:  # noqa: ANN001
    path.write_text(payload, encoding="utf-8")


def test_reads_valid_window_as_utc(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    path = tmp_path / "maintenance.json"
    _write(
        path,
        '{"starts_at":"2026-09-25T12:00:00+03:00",'
        '"ends_at":"2026-09-25T12:03:00+03:00"}',
    )
    monkeypatch.setattr(maintenance, "MAINTENANCE_PATH", path)

    assert maintenance.read_window(datetime(2026, 9, 25, 9, 1, tzinfo=UTC)) == {
        "starts_at": "2026-09-25T09:00:00+00:00",
        "ends_at": "2026-09-25T09:03:00+00:00",
    }


def test_fails_closed_for_missing_malformed_and_expired_windows(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    path = tmp_path / "maintenance.json"
    monkeypatch.setattr(maintenance, "MAINTENANCE_PATH", path)
    now = datetime(2026, 9, 25, 9, tzinfo=UTC)

    assert maintenance.read_window(now) is None
    _write(path, "not json")
    assert maintenance.read_window(now) is None
    _write(
        path,
        '{"starts_at":"2026-09-25T08:00:00+00:00",'
        '"ends_at":"2026-09-25T08:01:00+00:00"}',
    )
    assert maintenance.read_window(now) is None
    _write(path, '{"starts_at":"2026-09-25T09:00:00","ends_at":"2026-09-25T09:01:00"}')
    assert maintenance.read_window(now) is None


def test_rejects_excessive_or_too_distant_windows(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    path = tmp_path / "maintenance.json"
    monkeypatch.setattr(maintenance, "MAINTENANCE_PATH", path)
    now = datetime(2026, 9, 25, 9, tzinfo=UTC)

    _write(
        path,
        '{"starts_at":"2026-09-25T09:00:00+00:00",'
        '"ends_at":"2026-09-25T09:16:00+00:00"}',
    )
    assert maintenance.read_window(now) is None
    future = now + timedelta(days=1, seconds=1)
    end = future + timedelta(minutes=1)
    _write(path, f'{{"starts_at":"{future.isoformat()}","ends_at":"{end.isoformat()}"}}')
    assert maintenance.read_window(now) is None
