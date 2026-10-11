"""План відновлює ownership/ACL без повторного виконання міграцій."""

from pathlib import Path

import psycopg
import pytest

from avelren.adoption_inventory import AdoptionError, capture, fingerprint
from avelren.adoption_plan import build_plan, decode_plan, encode_plan, plan_digest
from avelren.privilege_gate import audit


def read_snapshot(database):
    with psycopg.connect(database("admin"), options="-c default_transaction_read_only=on") as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        return capture(conn)


def execute(database, statements):
    with psycopg.connect(database("admin")) as conn:
        for statement in statements:
            conn.execute(statement)


def test_adoption_fresh_plan_has_no_changes(database):
    before = read_snapshot(database)
    plan = build_plan(before)
    assert plan.forward == plan.inverse == ()
    assert fingerprint(plan.expected) == fingerprint(before)
    assert plan_digest(decode_plan(encode_plan(plan))) == plan_digest(plan)


@pytest.mark.parametrize(
    "mutation",
    [
        "ALTER TABLE devices OWNER TO avelren_admin",
        "GRANT SELECT ON devices TO PUBLIC",
        "ALTER SCHEMA public OWNER TO pg_database_owner; GRANT CREATE ON SCHEMA public TO PUBLIC",
        "GRANT SELECT ON devices TO avelren_backup WITH GRANT OPTION",
        "GRANT UPDATE(secret_hash) ON devices TO avelren_notifier",
        "GRANT USAGE ON SEQUENCE surge_events_id_seq TO avelren_api WITH GRANT OPTION",
        "GRANT EXECUTE ON FUNCTION activate_admin_after_pin(uuid) TO PUBLIC",
        "ALTER FUNCTION activate_admin_after_pin(uuid) OWNER TO avelren_admin",
        "ALTER DEFAULT PRIVILEGES FOR ROLE avelren_migrator GRANT EXECUTE ON FUNCTIONS TO PUBLIC",
        "ALTER DEFAULT PRIVILEGES FOR ROLE avelren_migrator IN SCHEMA public "
        "GRANT SELECT ON TABLES TO avelren_api",
    ],
)
def test_adoption_forward_inverse_exact_roundtrip(database, mutation):
    execute(database, [mutation])
    before = read_snapshot(database)
    plan = build_plan(before)
    assert plan.forward and plan.inverse
    execute(database, plan.forward)
    after = read_snapshot(database)
    assert fingerprint(after) == fingerprint(plan.expected)
    migrations = Path(__file__).resolve().parents[4] / "db/migrations"
    with psycopg.connect(database("admin"), options="-c default_transaction_read_only=on") as conn:
        assert audit(conn, migrations) == []
    execute(database, plan.inverse)
    assert fingerprint(read_snapshot(database)) == fingerprint(before)


@pytest.mark.parametrize(
    "mutation",
    [
        "UPDATE schema_migrations SET sha256=repeat('0',64) WHERE version='016_surge_monitor'",
        "CREATE TABLE public.unknown_object(id int)",
        "ALTER TABLE devices ADD COLUMN hidden_secret text",
        "ALTER TABLE observations DROP CONSTRAINT observations_wait_time_status_check",
        "ALTER FUNCTION activate_admin_after_pin(uuid) SECURITY INVOKER",
        "CREATE OR REPLACE FUNCTION activate_admin_after_pin(candidate uuid) RETURNS void "
        "LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp "
        "AS $$ BEGIN NULL; END $$",
    ],
)
def test_adoption_refuses_unsupported_schema_without_mutation(database, mutation):
    execute(database, [mutation])
    before = read_snapshot(database)
    with pytest.raises(AdoptionError):
        build_plan(before)
    assert fingerprint(read_snapshot(database)) == fingerprint(before)
