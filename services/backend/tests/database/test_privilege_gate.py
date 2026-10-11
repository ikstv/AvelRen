"""Gate має відхиляти drift і залишати дані/ACL незмінними."""

import json
import os
import subprocess
import sys

import psycopg
import pytest


def run_gate(database):
    env = {**os.environ, "AVELREN_PRIVILEGE_AUDIT_DSN": database("admin")}
    return subprocess.run(
        [sys.executable, "-m", "avelren.privilege_gate"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def fingerprint(database):
    with psycopg.connect(database("admin")) as conn:
        return conn.execute("""
            SELECT md5(string_agg(version || sha256 || applied_at::text, ',' ORDER BY version)),
                   (SELECT count(*) FROM devices),
                   (SELECT count(*) FROM collector_runs),
                   (SELECT md5(string_agg(oid::text || coalesce(relacl::text, ''),
                       ',' ORDER BY oid))
                      FROM pg_class WHERE relnamespace='public'::regnamespace)
            FROM schema_migrations
        """).fetchone()


def test_gate_accepts_current_schema_without_mutation(database):
    before = fingerprint(database)
    result = run_gate(database)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"status": "pass", "violations": []}
    assert fingerprint(database) == before


@pytest.mark.parametrize(
    "statement, category",
    [
        ("GRANT DELETE ON observations TO avelren_collector", "table_acl"),
        ("GRANT SELECT ON observations TO avelren_backup WITH GRANT OPTION", "table_acl"),
        ("REVOKE SELECT ON surge_predictions FROM avelren_backup", "table_acl"),
        ("GRANT UPDATE(secret_hash) ON devices TO avelren_notifier", "column_acl"),
        ("GRANT SELECT(id) ON devices TO avelren_notifier WITH GRANT OPTION", "column_acl"),
        ("GRANT UPDATE ON SEQUENCE surge_events_id_seq TO avelren_api", "sequence_acl"),
        (
            "GRANT USAGE ON SEQUENCE surge_events_id_seq TO avelren_surge WITH GRANT OPTION",
            "sequence_acl",
        ),
        ("GRANT EXECUTE ON FUNCTION activate_admin_after_pin(uuid) TO PUBLIC", "function_acl"),
        (
            "GRANT EXECUTE ON FUNCTION activate_admin_after_pin(uuid) "
            "TO avelren_api WITH GRANT OPTION",
            "function_acl",
        ),
        ("ALTER FUNCTION activate_admin_after_pin(uuid) SECURITY INVOKER", "function_definition"),
        (
            "ALTER FUNCTION activate_admin_after_pin(uuid) SET search_path=public",
            "function_definition",
        ),
        (
            "ALTER FUNCTION activate_admin_after_pin(uuid) OWNER TO avelren_admin",
            "function_definition",
        ),
        ("GRANT CREATE ON SCHEMA public TO avelren_api", "schema_acl"),
        ("GRANT USAGE ON SCHEMA public TO avelren_api WITH GRANT OPTION", "schema_acl"),
        ("GRANT TEMP ON DATABASE {database} TO avelren_api", "database_acl"),
        ("GRANT CONNECT ON DATABASE {database} TO avelren_api WITH GRANT OPTION", "database_acl"),
        (
            "ALTER DEFAULT PRIVILEGES FOR ROLE avelren_migrator "
            "GRANT EXECUTE ON FUNCTIONS TO PUBLIC",
            "default_acl",
        ),
        (
            "ALTER DEFAULT PRIVILEGES FOR ROLE avelren_migrator IN SCHEMA public "
            "GRANT SELECT ON TABLES TO avelren_api",
            "default_acl",
        ),
        ("ALTER TABLE surge_events OWNER TO avelren_admin", "relation_owner"),
        ("CREATE TABLE public.unexpected(id int)", "relation_inventory"),
        (
            "UPDATE schema_migrations SET sha256=repeat('0',64) "
            "WHERE version='015_wait_time_status'",
            "migration_journal",
        ),
    ],
)
def test_gate_rejects_acl_and_schema_drift_without_repair(database, statement, category):
    with psycopg.connect(database("admin")) as conn:
        name = conn.info.dbname
        conn.execute(statement.format(database=name))
    before = fingerprint(database)
    result = run_gate(database)
    assert result.returncode == 1, result.stderr
    assert category in json.loads(result.stdout)["violations"]
    assert fingerprint(database) == before


def test_gate_refuses_missing_dsn_without_exposing_secrets():
    env = {k: v for k, v in os.environ.items() if k != "AVELREN_PRIVILEGE_AUDIT_DSN"}
    result = subprocess.run(
        [sys.executable, "-m", "avelren.privilege_gate"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "Traceback" not in result.stderr
    assert "DATABASE_URL" not in result.stderr


@pytest.mark.parametrize(
    "change, restore, category",
    [
        (
            "ALTER ROLE avelren_api SUPERUSER",
            "ALTER ROLE avelren_api NOSUPERUSER",
            "role_capabilities",
        ),
        (
            "ALTER ROLE avelren_api BYPASSRLS",
            "ALTER ROLE avelren_api NOBYPASSRLS",
            "role_capabilities",
        ),
        ("ALTER ROLE avelren_api INHERIT", "ALTER ROLE avelren_api NOINHERIT", "role_capabilities"),
        (
            "GRANT avelren_migrator TO avelren_api",
            "REVOKE avelren_migrator FROM avelren_api",
            "role_memberships",
        ),
    ],
)
def test_gate_rejects_role_escalation(database, change, restore, category):
    try:
        with psycopg.connect(database("admin")) as conn:
            conn.execute(change)
        result = run_gate(database)
        assert result.returncode == 1, result.stderr
        assert category in json.loads(result.stdout)["violations"]
    finally:
        with psycopg.connect(database("admin")) as conn:
            conn.execute(restore)


def test_gate_overrides_writable_dsn_options(database):
    env = {
        **os.environ,
        "AVELREN_PRIVILEGE_AUDIT_DSN": psycopg.conninfo.make_conninfo(
            database("admin"),
            options="-c default_transaction_read_only=off",
        ),
    }
    before = fingerprint(database)
    result = subprocess.run(
        [sys.executable, "-m", "avelren.privilege_gate"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert fingerprint(database) == before
