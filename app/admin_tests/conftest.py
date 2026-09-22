"""Isolated PostgreSQL tests for administration, not a substitute for full Timescale CI."""

import hashlib
import os
import secrets
import sys
import uuid
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row

from avelren import db, ratelimit
from avelren.admin_pin import hash_pin
from avelren.api import app
from avelren.config import settings

if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


@pytest.fixture(scope="session")
def test_dsn():
    dsn = os.environ.get("ADMIN_ACCESS_TEST_DSN", "")
    if not dsn:
        pytest.skip("ADMIN_ACCESS_TEST_DSN is required for isolated PostgreSQL tests")
    config = conninfo_to_dict(dsn)
    if (
        os.environ.get("AVELREN_ADMIN_TEST_DB") != "1"
        or not config.get("dbname", "").startswith("avelren_admin_test")
        or config.get("host") not in {"127.0.0.1", "localhost", "::1"}
    ):
        pytest.fail("Refusing a non-local or non-test database")
    with psycopg.connect(dsn, autocommit=True) as conn:
        if conn.execute("SELECT to_regclass('public.devices')").fetchone()[0] is not None:
            pytest.fail("Use a fresh test database, not a reused application database")
        for role in ("avelren_api", "avelren_backup", "avelren_migrator"):
            if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)).fetchone():
                conn.execute(
                    psycopg.sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                        psycopg.sql.Identifier(role),
                        psycopg.sql.Literal(config.get("password", secrets.token_urlsafe(32))),
                    )
                )
        conn.execute("GRANT USAGE, CREATE ON SCHEMA public TO avelren_migrator")
        conn.execute("GRANT USAGE ON SCHEMA public TO avelren_api, avelren_backup")
        conn.execute("SET ROLE avelren_migrator")
        conn.execute("""
            CREATE TABLE devices (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                fcm_token text UNIQUE, platform text NOT NULL DEFAULT 'android',
                created_at timestamptz NOT NULL DEFAULT now(),
                last_seen timestamptz NOT NULL DEFAULT now(),
                is_admin boolean NOT NULL DEFAULT false, secret_hash text
            );
            CREATE TABLE schema_migrations(version text PRIMARY KEY);
            INSERT INTO schema_migrations VALUES ('011_admin_access');
            GRANT SELECT ON schema_migrations TO avelren_api;
            GRANT SELECT ON devices TO avelren_api;
            GRANT UPDATE(last_seen, fcm_token) ON devices TO avelren_api;
        """)
        migration = Path(__file__).resolve().parents[2] / "db/migrations/011_admin_access.sql"
        conn.execute(migration.read_text(encoding="utf-8"))
        conn.execute("RESET ROLE")
    return dsn


@pytest.fixture
def owner(test_dsn):
    with psycopg.connect(test_dsn, autocommit=True, row_factory=dict_row) as conn:
        conn.execute("UPDATE admin_access SET approved_device_id=NULL, pin_hash=NULL, "
                     "failures=0, locked_until=NULL WHERE singleton")
        conn.execute("DELETE FROM devices")
        yield conn


@pytest.fixture
def installation(owner):
    def create():
        secret = secrets.token_urlsafe(32)
        row = owner.execute(
            "INSERT INTO devices(fcm_token, secret_hash) VALUES (%s,%s) RETURNING id",
            (f"test-{uuid.uuid4()}", hashlib.sha256(secret.encode()).hexdigest()),
        ).fetchone()
        return {"X-Device-Id": str(row["id"]), "X-Device-Secret": secret}
    return create


@pytest.fixture
def approved(owner, installation):
    headers = installation()
    owner.execute("UPDATE admin_access SET approved_device_id=%s, pin_hash=%s WHERE singleton",
                  (headers["X-Device-Id"], hash_pin("7392")))
    return headers


@pytest.fixture
def client(test_dsn, owner):
    previous = settings.database_url
    settings.database_url = make_conninfo(test_dsn, user="avelren_api")
    db._pool = None
    ratelimit._hits.clear()
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        settings.database_url = previous
        db._pool = None
