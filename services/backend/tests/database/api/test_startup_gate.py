"""New API refuses historical schemas before serving requests."""

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize("database", [9, 10, 11, 13], indirect=True)
def test_new_api_refuses_old_schema_and_closes_pool(database, conn, monkeypatch):
    from avelren import db, ratelimit
    from avelren.api import app
    from avelren.config import settings
    from avelren.schema_gate import SchemaTooOldError

    journal = "SELECT version,sha256,applied_at FROM schema_migrations ORDER BY version"
    before = conn.execute(journal).fetchall()
    monkeypatch.setattr(settings, "database_url", database("api"))
    monkeypatch.setattr(db, "_pool", None)
    ratelimit._hits.clear()
    try:
        with pytest.raises(SchemaTooOldError, match="requires at least 015_wait_time_status"):
            with TestClient(app):
                pytest.fail("old schema unexpectedly started the new API")
        assert db._pool is not None and db._pool.closed
        assert conn.execute(journal).fetchall() == before
    finally:
        db._pool = None
        ratelimit._hits.clear()
