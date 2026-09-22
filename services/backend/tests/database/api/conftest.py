"""API працює під сервісною роллю в окремій БД кожного тесту."""

import hashlib
import secrets
from dataclasses import dataclass

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row


@dataclass(frozen=True)
class Installation:
    device_id: str
    device_secret: str

    def headers(self):
        return {"X-Device-Id": self.device_id, "X-Device-Secret": self.device_secret}


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
    finally:
        db._pool = None
        ratelimit._hits.clear()
