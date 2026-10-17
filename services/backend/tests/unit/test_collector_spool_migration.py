"""Explicit legacy evidence is bound to one retained cycle, never a whole spool."""

import asyncio
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from avelren.collector_spool import SpoolStore
from avelren.echerha import FetchResult

AT = datetime(2026, 10, 1, tzinfo=UTC)
SOURCE = "4503477f334c72ab05409bf241779592d2fe0bf1"
IMAGE = "sha256:40219d6c8ceee5a862382dbb62fe3df06181a20488635d47c5a965512eda9a72"


def test_marker_is_bound_to_exact_cycle_and_runtime(tmp_path):
    from avelren.collector_spool_migration import legacy_marker, migrated_legacy_cycle
    from avelren.paired_backup_spool import decode_cycle

    store = SpoolStore(tmp_path / "spool.sqlite3")
    store.finish(store.begin(AT), FetchResult(None, 500, 5, None, "HTTP 500"), 1)
    row = store.conn.execute(
        "SELECT seq,at,payload_version,payload,payload_sha256 FROM cycles"
    ).fetchone()
    cycle = decode_cycle(row)
    marker = legacy_marker(row, cycle, SOURCE, IMAGE)
    store.conn.execute("INSERT INTO meta VALUES('legacy_verified:1',?)", (marker,))
    assert migrated_legacy_cycle(store, cycle)
    for field, value in [("source_commit", "f" * 40), ("image_id", "sha256:" + "f" * 64),
                         ("seq", 2), ("at", "2026-10-02T00:00:00+00:00"),
                         ("payload_version", 2), ("payload_sha256", "a" * 64),
                         ("primary_sha256", "b" * 64)]:
        damaged = json.loads(marker)
        damaged[field] = value
        store.conn.execute("UPDATE meta SET value=? WHERE key='legacy_verified:1'",
                           (json.dumps(damaged),))
        with pytest.raises(ValueError):
            migrated_legacy_cycle(store, cycle)
    store.close()


def test_unknown_source_refused_before_any_sql_or_sqlite_write(tmp_path):
    from avelren.collector_spool_migration import migrate_legacy_spool

    store = SpoolStore(tmp_path / "spool.sqlite3")
    before = store.conn.execute("SELECT * FROM meta").fetchall()
    conn = AsyncMock()
    with pytest.raises(ValueError):
        asyncio.run(migrate_legacy_spool(store, conn, source_commit="f" * 40, image_id=IMAGE))
    conn.execute.assert_not_awaited()
    assert store.conn.execute("SELECT * FROM meta").fetchall() == before
    store.close()
