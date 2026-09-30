"""API працює під сервісною роллю в окремій БД кожного тесту."""

import hashlib
import secrets
from contextlib import asynccontextmanager
from dataclasses import dataclass

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg.rows import dict_row


@dataclass(frozen=True)
class Installation:
    device_id: str
    device_secret: str

    def headers(self):
        return {"X-Device-Id": self.device_id, "X-Device-Secret": self.device_secret}


def old_schema_component_app():
    """Exercise actual route handlers on historical schema, not startup compatibility."""
    from avelren import db
    from avelren.admin_access_api import router as access_router
    from avelren.api import app as production_app
    from avelren.config import settings
    from avelren.subscriptions_api import router as subscriptions_router

    @asynccontextmanager
    async def component_lifespan(_app):
        pool = db.get_pool(settings.api_statement_timeout_ms)
        await pool.open(wait=True, timeout=30)
        try:
            yield
        finally:
            await pool.close()

    component = FastAPI(lifespan=component_lifespan)
    paths = {"/health", "/workload", "/admin/telemetry", "/admin/access"}
    component.router.routes.extend(
        route
        for source in (production_app.router, access_router, subscriptions_router)
        for route in source.routes
        if getattr(route, "path", None) in paths
    )
    return component


@pytest.fixture
def conn(database):
    with psycopg.connect(database("admin"), autocommit=True, row_factory=dict_row) as connection:
        yield connection


@pytest.fixture
def checkpoint(conn):
    cid = 900_000_001
    conn.execute(
        "INSERT INTO checkpoints (id, title, for_vehicle_type, country_name) "
        "VALUES (%s, 'synthetic', 1, 'test')",
        (cid,),
    )
    return cid


@pytest.fixture
def installation(conn):
    def create():
        secret = secrets.token_urlsafe(32)
        row = conn.execute(
            "INSERT INTO devices (fcm_token, secret_hash) VALUES (%s, %s) RETURNING id",
            (f"synthetic-{secrets.token_hex(16)}", hashlib.sha256(secret.encode()).hexdigest()),
        ).fetchone()
        return Installation(str(row["id"]), secret)

    return create


@pytest.fixture
def device(installation):
    return installation()


@pytest.fixture
def approved(conn, device):
    from avelren.admin_pin import hash_pin

    conn.execute(
        "UPDATE admin_access SET approved_device_id=%s, pin_hash=%s WHERE singleton",
        (device.device_id, hash_pin("7392")),
    )
    return device.headers()


@pytest.fixture
def api_client(database, monkeypatch):
    from avelren import db, ratelimit
    from avelren.api import app
    from avelren.config import settings

    monkeypatch.setattr(settings, "database_url", database("api"))
    monkeypatch.setattr(db, "_pool", None)
    ratelimit._hits.clear()
    try:
        with TestClient(app) as client:
            yield client
        assert db._pool is not None and db._pool.closed, "API lifespan must close its pool"
    finally:
        db._pool = None
        ratelimit._hits.clear()


@pytest.fixture
def old_schema_component_client(database, monkeypatch):
    from avelren import db, ratelimit
    from avelren.config import settings

    monkeypatch.setattr(settings, "database_url", database("api"))
    monkeypatch.setattr(db, "_pool", None)
    ratelimit._hits.clear()
    try:
        with TestClient(old_schema_component_app()) as client:
            yield client
        assert db._pool is not None and db._pool.closed
    finally:
        db._pool = None
        ratelimit._hits.clear()
