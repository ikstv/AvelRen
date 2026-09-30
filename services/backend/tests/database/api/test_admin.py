"""Admin на справжніх міграціях, без службового доступу в HTTP-обробників."""

from concurrent.futures import ThreadPoolExecutor

import pytest


def attempt(client, headers, pin="0000"):
    response = client.post("/admin/access", headers=headers, json={"pin": pin})
    assert response.status_code == 200, response.text
    return response.json()



def test_foreign_wrong_pin_uses_shared_counter(api_client, approved, installation, conn):
    assert api_client.get("/admin/access").status_code == 401
    foreign = installation().headers()
    assert attempt(api_client, foreign, "0000")["attempts_remaining"] == 2
    assert conn.execute("SELECT failures FROM admin_access").fetchone()["failures"] == 1
    assert attempt(api_client, approved, "0000")["attempts_remaining"] == 1
    blocked = attempt(api_client, foreign, "0000")
    assert blocked["state"] == "blocked"
    assert attempt(api_client, approved, "7392") == blocked
    assert conn.execute(
        "SELECT admin_blocked_until FROM devices WHERE id=%s",
        (foreign["X-Device-Id"],),
    ).fetchone()["admin_blocked_until"] is None


def test_lock_survives_reinstallation(api_client, approved, installation, conn):
    assert attempt(api_client, approved)["attempts_remaining"] == 2
    assert attempt(api_client, approved)["attempts_remaining"] == 1
    blocked = attempt(api_client, approved)
    assert blocked["state"] == "blocked"
    hours = conn.execute(
        "SELECT extract(epoch FROM locked_until-clock_timestamp())/3600 AS hours FROM admin_access"
    ).fetchone()["hours"]
    assert 719.99 < hours <= 720
    fresh = installation().headers()
    assert attempt(api_client, fresh, "7392") == blocked
    assert attempt(api_client, approved, "7392") == blocked


def test_foreign_expired_lock_still_requires_pin(api_client, approved, installation, conn):
    foreign = installation().headers()
    conn.execute(
        "UPDATE devices SET admin_blocked_until=now()+interval '1 day' WHERE id=%s",
        (foreign["X-Device-Id"],),
    )
    assert attempt(api_client, foreign, "7392")["state"] == "blocked"
    conn.execute(
        "UPDATE devices SET admin_blocked_until=now()-interval '1 second' WHERE id=%s",
        (foreign["X-Device-Id"],),
    )
    assert api_client.get("/admin/access", headers=foreign).json()["state"] == "ready"
    assert attempt(api_client, foreign, "7392")["state"] == "authorized"


def test_foreign_status_never_consumes_attempt(api_client, approved, installation, conn):
    foreign = installation().headers()
    assert api_client.get("/admin/access", headers=foreign).json()["state"] == "ready"
    assert conn.execute("SELECT failures FROM admin_access").fetchone()["failures"] == 0
    assert attempt(api_client, foreign, "0000")["state"] == "invalid_pin"
    before = conn.execute("SELECT failures FROM admin_access").fetchone()["failures"]
    assert api_client.get("/admin/access", headers=foreign).json()["attempts_remaining"] == 2
    assert conn.execute("SELECT failures FROM admin_access").fetchone()["failures"] == before
    assert conn.execute(
        "SELECT admin_blocked_until FROM devices WHERE id=%s", (foreign["X-Device-Id"],)
    ).fetchone()["admin_blocked_until"] is None


@pytest.mark.parametrize("database", [11], indirect=True)
def test_without_installation_lock_migration_is_unavailable(
    database, old_schema_component_client, device
):
    assert attempt(old_schema_component_client, device.headers(), "7392")["state"] == "unavailable"



def test_only_one_admin_and_revocation(api_client, approved, installation, conn):
    from avelren.admin_enroll import set_admin

    old = installation()
    conn.execute("UPDATE devices SET is_admin=true WHERE id=%s", (old.device_id,))
    assert attempt(api_client, approved, "7392")["state"] == "authorized"
    assert api_client.get("/admin/telemetry", headers=approved).status_code == 200
    rows = conn.execute("SELECT id FROM devices WHERE is_admin").fetchall()
    assert [str(row["id"]) for row in rows] == [approved["X-Device-Id"]]
    assert set_admin(conn, approved["X-Device-Id"], False) == 0
    assert attempt(api_client, approved, "7392")["state"] == "authorized"



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
def test_without_admin_migration_core_remains_available(
    database, old_schema_component_client, device
):
    assert old_schema_component_client.get("/health").status_code == 200
    assert old_schema_component_client.get("/workload").status_code == 200
    assert attempt(old_schema_component_client, device.headers(), "7392")["state"] == "unavailable"



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



def test_new_installation_can_take_admin_after_correct_pin(
    api_client, approved, installation, conn
):
    assert attempt(api_client, approved, "7392")["state"] == "authorized"
    fresh = installation().headers()
    before = conn.execute(
        "SELECT approved_device_id, failures, locked_until FROM admin_access"
    ).fetchone().copy()
    ready = api_client.get("/admin/access", headers=fresh).json()
    assert ready == {"state": "ready", "attempts_remaining": 3, "locked_until": None}
    assert conn.execute(
        "SELECT approved_device_id, failures, locked_until FROM admin_access"
    ).fetchone() == before
    assert attempt(api_client, fresh, "7392")["state"] == "authorized"
    admins = conn.execute("SELECT id FROM devices WHERE is_admin").fetchall()
    assert [str(row["id"]) for row in admins] == [fresh["X-Device-Id"]]
    assert str(conn.execute(
        "SELECT approved_device_id FROM admin_access"
    ).fetchone()["approved_device_id"]) == fresh["X-Device-Id"]
    assert api_client.get("/admin/telemetry", headers=approved).status_code == 403
    assert api_client.get("/admin/telemetry", headers=fresh).status_code == 200



@pytest.mark.parametrize("database", [13], indirect=True)
def test_new_installation_stays_closed_without_014(
    database, old_schema_component_client, approved, installation, conn
):
    fresh = installation().headers()
    status = old_schema_component_client.get("/admin/access", headers=fresh)
    assert status.json()["state"] == "awaiting_approval"
    assert attempt(old_schema_component_client, fresh, "7392")["state"] == "blocked"
    assert conn.execute("SELECT failures FROM admin_access").fetchone()["failures"] == 0



def test_installation_without_fcm_cannot_take_admin(api_client, approved, installation, conn):
    fresh = installation().headers()
    conn.execute(
        "UPDATE devices SET fcm_token=NULL WHERE id=%s", (fresh["X-Device-Id"],)
    )
    assert api_client.get("/admin/access", headers=fresh).json()["state"] == "unavailable"
    assert attempt(api_client, fresh, "7392")["state"] == "unavailable"
    row = conn.execute("SELECT approved_device_id, failures FROM admin_access").fetchone()
    assert str(row["approved_device_id"]) == approved["X-Device-Id"]
    assert row["failures"] == 0
    assert conn.execute("SELECT count(*) AS n FROM devices WHERE is_admin").fetchone()["n"] == 0



def test_third_error_and_correct_pin_are_serialized(
    api_client, approved, installation, conn
):
    fresh = installation().headers()
    conn.execute("UPDATE admin_access SET failures=2 WHERE singleton")
    with ThreadPoolExecutor(max_workers=2) as pool:
        wrong = pool.submit(attempt, api_client, approved, "0000")
        correct = pool.submit(attempt, api_client, fresh, "7392")
        states = [wrong.result()["state"], correct.result()["state"]]
    row = conn.execute(
        "SELECT approved_device_id, failures, locked_until FROM admin_access"
    ).fetchone()
    admins = conn.execute("SELECT id FROM devices WHERE is_admin").fetchall()
    if states == ["blocked", "blocked"]:
        assert row["failures"] == 3 and row["locked_until"] is not None
        assert str(row["approved_device_id"]) == approved["X-Device-Id"]
        assert admins == []
    else:
        assert states == ["invalid_pin", "authorized"]
        assert row["failures"] == 1 and row["locked_until"] is None
        assert str(row["approved_device_id"]) == fresh["X-Device-Id"]
        assert [str(admin["id"]) for admin in admins] == [fresh["X-Device-Id"]]
