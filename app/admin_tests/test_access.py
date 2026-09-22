from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from psycopg.conninfo import make_conninfo


def attempt(client, headers, pin="0000"):
    response = client.post("/admin/access", headers=headers, json={"pin": pin})
    assert response.status_code == 200, response.text
    return response.json()


def test_requires_installation_secret(client, approved):
    assert client.get("/admin/access").status_code == 401
    assert client.post("/admin/access", headers={"X-Device-Id": approved["X-Device-Id"]},
                       json={"pin": "7392"}).status_code == 401


def test_unknown_installation_cannot_guess_pin_or_lock_owner(client, approved, installation, owner):
    foreign = installation()
    assert attempt(client, foreign, "7392")["state"] == "awaiting_approval"
    assert owner.execute("SELECT failures FROM admin_access").fetchone()["failures"] == 0


def test_three_failures_persist_and_correct_pin_cannot_bypass_lock(client, approved, owner):
    assert attempt(client, approved)["attempts_remaining"] == 2
    assert attempt(client, approved)["attempts_remaining"] == 1
    blocked = attempt(client, approved)
    assert blocked["state"] == "blocked"
    hours = owner.execute(
        "SELECT extract(epoch FROM locked_until-clock_timestamp())/3600 AS hours FROM admin_access"
    ).fetchone()["hours"]
    assert 23.99 < hours <= 24
    assert attempt(client, approved, "7392") == blocked
    assert client.get("/admin/access", headers=approved).json()["state"] == "blocked"
    assert owner.execute("SELECT count(*) AS n FROM devices WHERE is_admin").fetchone()["n"] == 0


def test_approval_of_reinstall_does_not_reset_block(client, approved, installation, owner):
    for _ in range(3):
        attempt(client, approved)
    fresh = installation()
    owner.execute("UPDATE admin_access SET approved_device_id=%s", (fresh["X-Device-Id"],))
    assert attempt(client, fresh, "7392")["state"] == "blocked"
    assert attempt(client, approved, "7392")["state"] == "awaiting_approval"


def test_expired_lock_starts_with_three_attempts(client, approved, owner):
    owner.execute("UPDATE admin_access SET failures=3, locked_until=now()-interval '1 second'")
    assert client.get("/admin/access", headers=approved).json()["attempts_remaining"] == 3
    assert attempt(client, approved)["attempts_remaining"] == 2


def test_success_atomically_replaces_old_admin(client, approved, installation, owner):
    old = installation()
    owner.execute("UPDATE devices SET is_admin=true WHERE id=%s", (old["X-Device-Id"],))
    attempt(client, approved)
    assert attempt(client, approved, "7392")["state"] == "authorized"
    rows = owner.execute("SELECT id FROM devices WHERE is_admin").fetchall()
    assert [str(row["id"]) for row in rows] == [approved["X-Device-Id"]]
    assert owner.execute("SELECT failures FROM admin_access").fetchone()["failures"] == 0


def test_parallel_attempts_are_serialized(client, approved, owner):
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _: attempt(client, approved), range(5)))
    assert sorted(row["attempts_remaining"] for row in results) == [0, 0, 0, 1, 2]
    assert owner.execute("SELECT failures FROM admin_access").fetchone()["failures"] == 3


def test_api_cannot_approve_device_or_directly_promote(test_dsn, approved):
    with psycopg.connect(make_conninfo(test_dsn, user="avelren_api"), autocommit=True) as conn:
        for statement in (
            "UPDATE admin_access SET approved_device_id=NULL",
            "UPDATE admin_access SET pin_hash='forged'",
            "UPDATE devices SET is_admin=true",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(statement)


def test_sql_function_refuses_unapproved_or_blocked_target(test_dsn, approved, installation, owner):
    foreign = installation()
    with psycopg.connect(make_conninfo(test_dsn, user="avelren_api"), autocommit=True) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT activate_approved_admin(%s::uuid)", (foreign["X-Device-Id"],))
        owner.execute("UPDATE admin_access SET failures=3, locked_until=now()+interval '24 hours'")
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT activate_approved_admin(%s::uuid)", (approved["X-Device-Id"],))


def test_backup_has_read_access_but_cannot_activate(test_dsn, approved):
    with psycopg.connect(make_conninfo(test_dsn, user="avelren_backup"), autocommit=True) as conn:
        assert conn.execute("SELECT count(*) FROM admin_access").fetchone()[0] == 1
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT activate_approved_admin(%s::uuid)", (approved["X-Device-Id"],))


def test_database_rejects_two_administrators(owner, installation):
    first, second = installation(), installation()
    owner.execute("UPDATE devices SET is_admin=true WHERE id=%s", (first["X-Device-Id"],))
    with pytest.raises(psycopg.errors.UniqueViolation):
        owner.execute("UPDATE devices SET is_admin=true WHERE id=%s", (second["X-Device-Id"],))


def test_missing_feature_migration_disables_access_not_core(client, approved, owner):
    owner.execute("DELETE FROM schema_migrations WHERE version='011_admin_access'")
    try:
        assert attempt(client, approved, "7392")["state"] == "unavailable"
        assert client.get("/admin/access", headers=approved).json()["state"] == "unavailable"
        from avelren.schema_gate import required_schema_version

        assert required_schema_version() == "009_observability"
    finally:
        owner.execute("INSERT INTO schema_migrations VALUES ('011_admin_access')")


def test_approval_command_preserves_lock(test_dsn, owner, approved, installation, monkeypatch):
    import sys

    from avelren import admin_approve
    from avelren.config import settings

    fresh = installation()
    owner.execute("UPDATE admin_access SET failures=3, locked_until=now()+interval '24 hours'")
    before = owner.execute("SELECT locked_until FROM admin_access").fetchone()["locked_until"]
    monkeypatch.setattr(settings, "database_url", test_dsn)
    monkeypatch.setattr(sys, "argv", ["admin_approve", fresh["X-Device-Id"]])
    admin_approve.main()
    row = owner.execute(
        "SELECT approved_device_id, failures, locked_until FROM admin_access"
    ).fetchone()
    assert str(row["approved_device_id"]) == fresh["X-Device-Id"]
    assert row["failures"] == 3
    assert row["locked_until"] == before


def test_invalid_body_never_echoes_stored_pin_hash(client, approved, owner):
    response = client.post("/admin/access", headers=approved, json={"pin": "x" * 129})
    assert response.status_code == 422
    encoded = owner.execute("SELECT pin_hash FROM admin_access").fetchone()["pin_hash"]
    assert encoded not in response.text


def test_wrong_length_and_letters_consume_attempts_without_format_hint(client, approved):
    assert attempt(client, approved, "a")["attempts_remaining"] == 2
    assert attempt(client, approved, "abcdef")["attempts_remaining"] == 1
    assert attempt(client, approved, "12345")["state"] == "blocked"


def test_activation_function_has_restricted_owner_and_path(owner):
    row = owner.execute(
        "SELECT p.prosecdef, pg_get_userbyid(p.proowner) AS owner, p.proconfig "
        "FROM pg_proc p WHERE p.oid='public.activate_approved_admin(uuid)'::regprocedure"
    ).fetchone()
    assert row["prosecdef"] is True
    assert row["owner"] == "avelren_migrator"
    assert "search_path=pg_catalog, pg_temp" in row["proconfig"]


def test_operator_revocation_also_revokes_pin_approval(client, approved, owner):
    from avelren.admin_enroll import set_admin

    assert attempt(client, approved, "7392")["state"] == "authorized"
    assert set_admin(owner, approved["X-Device-Id"], False) == 0
    assert attempt(client, approved, "7392")["state"] == "awaiting_approval"
