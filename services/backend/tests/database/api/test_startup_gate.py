"""New API refuses historical schemas before serving requests."""

import psycopg
import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize(
    ("database", "expected_error", "message"),
    [
        (9, psycopg.errors.InsufficientPrivilege, "permission denied for table schema_migrations"),
        (10, "schema", "requires at least 015_wait_time_status"),
        (11, "schema", "requires at least 015_wait_time_status"),
        (13, "schema", "requires at least 015_wait_time_status"),
    ],
    indirect=["database"],
)
def test_new_api_refuses_old_schema_and_closes_pool(
    database, expected_error, message, conn, monkeypatch
):
    from avelren import db, ratelimit
    from avelren.api import app
    from avelren.config import settings
    from avelren.schema_gate import SchemaTooOldError

    if expected_error == "schema":
        expected_error = SchemaTooOldError
    journal = "SELECT version,sha256,applied_at FROM schema_migrations ORDER BY version"
    before = conn.execute(journal).fetchall()
    monkeypatch.setattr(settings, "database_url", database("api"))
    monkeypatch.setattr(db, "_pool", None)
    ratelimit._hits.clear()
    try:
        with pytest.raises(expected_error, match=message):
            with TestClient(app):
                pytest.fail("old schema unexpectedly started the new API")
        assert db._pool is not None and db._pool.closed
        assert conn.execute(journal).fetchall() == before
    finally:
        db._pool = None
        ratelimit._hits.clear()
