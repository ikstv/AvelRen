"""Offline acceptance of the durable SQLite snapshot, including live WAL."""

import hashlib
import json
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from avelren.collector_spool import SpoolStore
from avelren.echerha import FetchResult
from avelren.paired_backup_spool import SpoolBackupError, inspect_spool, snapshot_spool

AT = datetime(2026, 10, 13, 1, tzinfo=UTC)


def populate(path, count=1):
    store = SpoolStore(path)
    for minute in range(count):
        seq = store.begin(AT + timedelta(minutes=minute))
        store.finish(seq, FetchResult(None, 500, 7, None, "HTTP 500"), 1)
    return store


def test_online_snapshot_preserves_pending_wal(tmp_path):
    source = tmp_path / "live" / "cycles.sqlite3"
    store = populate(source, 5)
    try:
        hashes = store.conn.execute("SELECT payload_sha256 FROM cycles ORDER BY seq").fetchall()
        assert Path(f"{source}-wal").stat().st_size > 0
        destination = tmp_path / "copy" / "spool.sqlite3"
        summary = snapshot_spool(source, destination)
        assert summary["state_counts"] == {"started": 0, "pending": 5, "acked": 0}
        assert summary["payload_count"] == 5
        assert summary["cycle_range"] == {
            "first_seq": 1,
            "last_seq": 5,
            "first_at": "2026-10-13T01:00:00+00:00",
            "last_at": "2026-10-13T01:04:00+00:00",
        }
        assert summary["sha256"] == hashlib.sha256(destination.read_bytes()).hexdigest()
        assert summary["bytes"] == destination.stat().st_size
        with sqlite3.connect(destination) as connection:
            assert (
                connection.execute("SELECT payload_sha256 FROM cycles ORDER BY seq").fetchall()
                == hashes
            )
        assert (
            store.conn.execute("SELECT payload_sha256 FROM cycles ORDER BY seq").fetchall()
            == hashes
        )
    finally:
        store.close()


def test_inspect_accepts_started_without_result(tmp_path):
    path = tmp_path / "copy.sqlite3"
    store = populate(path)
    store.ack(1)
    store.begin(AT + timedelta(minutes=1))
    store.close()
    before = path.read_bytes()
    summary = inspect_spool(path)
    assert summary["state_counts"] == {"started": 1, "pending": 0, "acked": 1}
    assert summary["payload_count"] == 1
    assert summary["schema_version"] == summary["payload_version"] == 1
    assert path.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["copy.sqlite3"]


@pytest.mark.parametrize(
    "damage", ["digest", "version", "incomplete", "model", "envelope", "schema"]
)
@pytest.mark.parametrize("acked", [False, True])
def test_invalid_pending_digest_or_version_fails(tmp_path, damage, acked):
    path = tmp_path / "copy.sqlite3"
    store = populate(path)
    if acked:
        store.ack(1)
    store.close()
    with sqlite3.connect(path) as connection:
        if damage == "digest":
            connection.execute("UPDATE cycles SET payload_sha256=?", ("0" * 64,))
        elif damage == "version":
            connection.execute("UPDATE cycles SET payload_version=999")
        elif damage == "incomplete":
            connection.execute("UPDATE cycles SET payload=NULL")
        elif damage == "schema":
            connection.execute("UPDATE meta SET value='999' WHERE key='schema_version'")
        else:
            data = json.loads(connection.execute("SELECT payload FROM cycles").fetchone()[0])
            if damage == "model":
                data["items"] = [{"id": 7, "title": "invalid"}]
            else:
                data["duration_ms"] = "secret payload"
            payload = json.dumps(data).encode()
            connection.execute(
                "UPDATE cycles SET payload=?,payload_sha256=?",
                (
                    payload,
                    hashlib.sha256(payload).hexdigest(),
                ),
            )
    connection.close()
    with pytest.raises(SpoolBackupError):
        inspect_spool(path)


def test_snapshot_destination_inside_live_directory_rejected(tmp_path):
    source = tmp_path / "live" / "cycles.sqlite3"
    store = populate(source)
    try:
        for destination in [
            source,
            source.parent / "copy.sqlite3",
            source.parent / "child" / "copy",
        ]:
            with pytest.raises(SpoolBackupError):
                snapshot_spool(source, destination)
    finally:
        store.close()


def test_inspect_missing_or_live_wal_rejected_without_creation(tmp_path):
    with pytest.raises(SpoolBackupError):
        inspect_spool(tmp_path / "missing.sqlite3")
    assert list(tmp_path.iterdir()) == []
    store = populate(tmp_path / "live.sqlite3")
    try:
        with pytest.raises(SpoolBackupError):
            inspect_spool(store.path)
    finally:
        store.close()


def test_cli_json_and_categorical_failure(tmp_path):
    path = tmp_path / "copy.sqlite3"
    populate(path).close()
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "avelren.paired_backup_spool",
            "inspect",
            "--source",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["payload_count"] == 1
    failure = subprocess.run(
        [
            sys.executable,
            "-m",
            "avelren.paired_backup_spool",
            "inspect",
            "--source",
            str(path / "secret"),
        ],
        capture_output=True,
        text=True,
    )
    assert failure.returncode != 0 and failure.stdout == ""
    assert "secret" not in failure.stderr and str(tmp_path) not in failure.stderr


def test_cli_online_snapshot(tmp_path):
    source = tmp_path / "live" / "cycles.sqlite3"
    destination = tmp_path / "output" / "spool.sqlite3"
    store = populate(source, 5)
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "avelren.paired_backup_spool",
                "snapshot",
                "--source",
                str(source),
                "--output",
                str(destination),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["state_counts"]["pending"] == 5
        assert inspect_spool(destination)["payload_count"] == 5
        if sys.platform != "win32":
            assert destination.parent.stat().st_mode & 0o777 == 0o700
            assert destination.stat().st_mode & 0o777 == 0o600
    finally:
        store.close()


def test_duplicate_payload_fields_and_unknown_layout_rejected(tmp_path):
    path = tmp_path / "copy.sqlite3"
    populate(path).close()
    with sqlite3.connect(path) as connection:
        data = connection.execute("SELECT payload FROM cycles").fetchone()[0]
        data = data.replace(b'"duration_ms":7', b'"duration_ms":7,"duration_ms":7')
        connection.execute(
            "UPDATE cycles SET payload=?,payload_sha256=?",
            (
                data,
                hashlib.sha256(data).hexdigest(),
            ),
        )
    connection.close()
    with pytest.raises(SpoolBackupError):
        inspect_spool(path)
    populate(tmp_path / "layout.sqlite3").close()
    with sqlite3.connect(tmp_path / "layout.sqlite3") as connection:
        connection.execute("CREATE TABLE future_schema(secret TEXT)")
    connection.close()
    with pytest.raises(SpoolBackupError):
        inspect_spool(tmp_path / "layout.sqlite3")


def test_snapshot_cleanup_failure_remains_categorical(tmp_path, monkeypatch):
    source = tmp_path / "live" / "invalid.sqlite3"
    source.parent.mkdir()
    source.write_bytes(b"invalid SQLite")
    destination = tmp_path / "output" / "copy.sqlite3"

    def denied_unlink(path, **kwargs):
        raise PermissionError("secret destination details")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", denied_unlink)
        with pytest.raises(SpoolBackupError) as failure:
            snapshot_spool(source, destination)
    assert "secret" not in str(failure.value)
