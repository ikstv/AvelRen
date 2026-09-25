"""Admin на справжніх міграціях, без службового доступу в HTTP-обробників."""

from concurrent.futures import ThreadPoolExecutor

import pytest


def attempt(client, headers, pin="0000"):
    response = client.post("/admin/access", headers=headers, json={"pin": pin})
    assert response.status_code == 200, response.text
    return response.json()


def test_unapproved_cannot_lock_owner(api_client, approved, installation, conn):
    assert api_client.get("/admin/access").status_code == 401
    foreign = installation().headers()
    deadline = None
    for _ in range(4):
        result = attempt(api_client, foreign, "7392")
        assert result["state"] == "blocked"
        if deadline is None:
            deadline = result["locked_until"]
        assert result["locked_until"] == deadline
    assert conn.execute("SELECT failures FROM admin_access").fetchone()["failures"] == 0
    hours = conn.execute(
        "SELECT extract(epoch FROM admin_blocked_until-clock_timestamp())/3600 AS hours "
        "FROM devices WHERE id=%s", (foreign["X-Device-Id"],),
    ).fetchone()["hours"]
    assert 23.99 < hours <= 24
    assert attempt(api_client, approved, "7392")["state"] == "authorized"


def test_lock_survives_reinstallation(api_client, approved, installation, conn):
    assert attempt(api_client, approved)["attempts_remaining"] == 2
    assert attempt(api_client, approved)["attempts_remaining"] == 1
    blocked = attempt(api_client, approved)
    assert blocked["state"] == "blocked"
    hours = conn.execute(
        "SELECT extract(epoch FROM locked_until-clock_timestamp())/3600 AS hours FROM admin_access"
    ).fetchone()["hours"]
    assert 23.99 < hours <= 24
    assert attempt(api_client, approved, "7392") == blocked
    fresh = installation().headers()
    conn.execute("UPDATE admin_access SET approved_device_id=%s", (fresh["X-Device-Id"],))
    assert attempt(api_client, fresh, "7392") == blocked
    assert attempt(api_client, approved, "7392")["state"] == "blocked"


def test_foreign_expired_lock_requires_approval(api_client, approved, installation, conn):
    foreign = installation().headers()
    assert attempt(api_client, foreign, "7392")["state"] == "blocked"
    conn.execute(
        "UPDATE devices SET admin_blocked_until=now()-interval '1 second' WHERE id=%s",
        (foreign["X-Device-Id"],),
    )
    assert attempt(api_client, foreign, "7392")["state"] == "blocked"
    assert attempt(api_client, approved, "7392")["state"] == "authorized"


def test_foreign_status_never_creates_or_extends_self_lock(api_client, approved, installation, conn):
    foreign = installation().headers()
    assert api_client.get("/admin/access", headers=foreign).json()["state"] == "awaiting_approval"
    assert conn.execute(
        "SELECT admin_blocked_until FROM devices WHERE id=%s", (foreign["X-Device-Id"],)
    ).fetchone()["admin_blocked_until"] is None

    # A PIN POST is an attempt, so it gets the foreign-installation lock.
    locked = attempt(api_client, foreign, "7392")
    assert locked["state"] == "blocked"
    before = conn.execute(
        "SELECT admin_blocked_until FROM devices WHERE id=%s", (foreign["X-Device-Id"],)
    ).fetchone()["admin_blocked_until"]
    assert api_client.get("/admin/access", headers=foreign).json() == locked
    after = conn.execute(
        "SELECT admin_blocked_until FROM devices WHERE id=%s", (foreign["X-Device-Id"],)
    ).fetchone()["admin_blocked_until"]
    assert after == before

    conn.execute(
        "UPDATE devices SET admin_blocked_until=now()-interval '1 second' WHERE id=%s",
        (foreign["X-Device-Id"],),
    )
    assert api_client.get("/admin/access", headers=foreign).json()["state"] == "awaiting_approval"
    assert conn.execute(
        "SELECT admin_blocked_until < clock_timestamp() AS expired FROM devices WHERE id=%s",
        (foreign["X-Device-Id"],),
    ).fetchone()["expired"] is True


@pytest.mark.parametrize("database", [11], indirect=True)
def test_without_installation_lock_migration_is_unavailable(database, api_client, device):
    assert attempt(api_client, device.headers(), "7392")["state"] == "unavailable"


def test_only_one_admin_and_revocation(api_client, approved, installation, conn):
    from avelren.admin_enroll import set_admin

    old = installation()
    conn.execute("UPDATE devices SET is_admin=true WHERE id=%s", (old.device_id,))
    assert attempt(api_client, approved, "7392")["state"] == "authorized"
    assert api_client.get("/admin/telemetry", headers=approved).status_code == 200
    rows = conn.execute("SELECT id FROM devices WHERE is_admin").fetchall()
    assert [str(row["id"]) for row in rows] == [approved["X-Device-Id"]]
    assert set_admin(conn, approved["X-Device-Id"], False) == 0
    assert attempt(api_client, approved, "7392")["state"] == "blocked"


def test_parallel_attempts_cannot_bypass_limit(api_client, approved, conn):
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _: attempt(api_client, approved), range(5)))
    assert sorted(row["attempts_remaining"] for row in results) == [0, 0, 0, 1, 2]
    assert conn.execute("SELECT failures FROM admin_access").fetchone()["failures"] == 3


def test_expired_lock_resets_attempts(api_client, approved, conn):
    conn.execute("UPDATE admin_access SET failures=3, locked_until=now()-interval '1 second'")
    assert api_client.get("/admin/access", headers=approved).json()["attempts_remaining"] == 3
    assert attempt(api_client, approved)["attempts_remaining"] == 2


@pytest.mark.parametrize("database", [10], indirect=True)
def test_without_admin_migration_core_remains_available(database, api_client, device):
    assert api_client.get("/health").status_code == 200
    assert api_client.get("/workload").status_code == 200
    assert attempt(api_client, device.headers(), "7392")["state"] == "unavailable"


def test_approval_command_preserves_lock(database, approved, installation, conn, monkeypatch):
    import sys

    from avelren import admin_approve
    from avelren.config import settings

    fresh = installation()
    conn.execute("UPDATE admin_access SET failures=3, locked_until=now()+interval '24 hours'")
    before = conn.execute("SELECT locked_until FROM admin_access").fetchone()["locked_until"]
    monkeypatch.setattr(settings, "database_url", database("admin"))
    monkeypatch.setattr(sys, "argv", ["admin_approve", fresh.device_id])
    admin_approve.main()
    row = conn.execute(
        "SELECT approved_device_id, failures, locked_until FROM admin_access"
    ).fetchone()
    assert str(row["approved_device_id"]) == fresh.device_id
    assert row["failures"] == 3
    assert row["locked_until"] == before
