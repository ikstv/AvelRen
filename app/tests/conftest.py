"""Shared groundwork for the DB tests.

Three requirements whose violation would cost more than the tests themselves.

1. **A test must not touch the live DB.** Previously `test_alerts.py` began with
   `DELETE FROM alerts WHERE threshold = 50` — in prod that would delete live
   alerts of real people. So the run is now fail-closed: without an explicit
   `AVELREN_TEST_DB=1` and without a test DB name, pytest exits BEFORE the first
   query, rather than "almost safely" deleting something.

2. **The application under test uses the least-privilege role.** `api_client`
   swaps the DSN for `API_DATABASE_URL` when it is set. Without that, a
   privileged run would hide a missing GRANT until production.

3. **A clean DB is the normal test environment.** The point reference list is
   filled by the collector, so on fresh migrations no checkpoint exists. Tests no
   longer rely on id 1 or 5: each creates its own synthetic point and removes
   only its own records.
"""

import asyncio
import hashlib
import os
import random
import secrets
import sys
from dataclasses import dataclass

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row


@dataclass(frozen=True)
class Installation:
    """Test installation: the pair a client uses to enter protected endpoints."""

    device_id: str
    device_secret: str

    def headers(self) -> dict[str, str]:
        return {"X-Device-Id": self.device_id, "X-Device-Secret": self.device_secret}

DSN = os.environ.get("DATABASE_URL", "")

# Synthetic ids live in advance in a range the source does not use: eCherha
# issues small numbers, so an overlap with the real reference list is impossible.
SYNTHETIC_ID_BASE = 900_000_000

# Windows gives a ProactorEventLoop by default, with which psycopg does not work
# at all in async mode. Prod runs on Linux, but the tests must run on a
# developer's machine too — otherwise the only way to run them is CI.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def pytest_configure(config: pytest.Config) -> None:
    """The safeguard fires before test collection — that is, before any DELETE."""
    if not DSN:
        pytest.exit("DATABASE_URL is not set", returncode=3)

    if os.environ.get("AVELREN_TEST_DB") != "1":
        pytest.exit(
            "The tests modify the DB. An explicit AVELREN_TEST_DB=1 is required — "
            "so that an accidental run does not hit the live database.",
            returncode=3,
        )

    dbname = (conninfo_to_dict(DSN).get("dbname") or "").lower()
    if "test" not in dbname and "ci" not in dbname:
        pytest.exit(
            f"DB '{dbname}' is not marked as a test one. The name must contain "
            "'test' or 'ci' — two independent signals are enough that hitting prod "
            "would take actually trying.",
            returncode=3,
        )


@pytest.fixture()
def conn():
    """A connection without shared state between tests."""
    with psycopg.connect(DSN, autocommit=True, row_factory=dict_row) as c:
        yield c


@pytest.fixture()
def checkpoint(conn) -> int:
    """A synthetic checkpoint that exists only within a single test.

    Cleanup goes in dependency order: devices cascade-remove subscriptions,
    alerts, and targets, then observations and the point itself disappear. The
    tests touch nothing that is not theirs.
    """
    cid = SYNTHETIC_ID_BASE + random.randrange(1, 1_000_000)
    conn.execute(
        """
        INSERT INTO checkpoints (id, title, for_vehicle_type, country_name)
        VALUES (%s, %s, 1, 'test')
        """,
        (cid, f"synthetic-{cid}"),
    )
    try:
        yield cid
    finally:
        conn.execute(
            "DELETE FROM devices WHERE id IN ("
            "  SELECT device_id FROM subscriptions WHERE checkpoint_id = %s"
            "  UNION SELECT device_id FROM eta_targets WHERE checkpoint_id = %s)",
            (cid, cid),
        )
        conn.execute("DELETE FROM alerts WHERE checkpoint_id = %s", (cid,))
        conn.execute("DELETE FROM eta_alerts WHERE checkpoint_id = %s", (cid,))
        conn.execute("DELETE FROM observations WHERE checkpoint_id = %s", (cid,))
        conn.execute("DELETE FROM checkpoints WHERE id = %s", (cid,))


@pytest.fixture()
def api_client():
    """FastAPI TestClient with a fresh pool per test.

    `avelren.db._pool` is a module-level singleton, and the lifespan does
    `pool.close()` when one TestClient closes. The next TestClient in the same
    session would fail on PoolClosed. Resetting _pool = None before opening
    guarantees a new pool per test — exactly what we want in prod too, when the
    process starts from scratch.
    """
    from fastapi.testclient import TestClient

    from avelren import db
    from avelren.api import app
    from avelren.config import settings

    # The application under test talks to the database as `avelren_api`, not as
    # an admin. Otherwise the whole application suite would pass even when the
    # production role is missing a GRANT: scripts/backend-test.sh hands pytest
    # an admin DATABASE_URL, and least privilege was verified only by the
    # hand-maintained matrix in test_db_privileges.py.
    # Scaffolding fixtures (`conn`) deliberately stay on the admin DSN: creating
    # and removing synthetic rows is the test's job, not the application's.
    role_dsn = os.environ.get("API_DATABASE_URL")
    previous_url = settings.database_url
    if role_dsn:
        settings.database_url = role_dsn
    db._pool = None
    try:
        with TestClient(app) as client:
            yield client
    finally:
        settings.database_url = previous_url
        db._pool = None


@pytest.fixture()
def device(conn) -> Installation:
    """A device with its own (id, secret) pair: without the secret, protected
    endpoints would respond 401, so tests without credentials simply would not work."""
    token = f"test-{random.randrange(10**12):012d}"
    secret = secrets.token_urlsafe(32)
    secret_hash = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    row = conn.execute(
        """
        INSERT INTO devices (fcm_token, secret_hash)
        VALUES (%s, %s)
        RETURNING id
        """,
        (token, secret_hash),
    ).fetchone()
    installation = Installation(device_id=str(row["id"]), device_secret=secret)
    try:
        yield installation
    finally:
        conn.execute("DELETE FROM devices WHERE id = %s", (installation.device_id,))
