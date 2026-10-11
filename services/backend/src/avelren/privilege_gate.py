"""Read-only звірка least-privilege контракту міграцій 001–016.

Походження: ikstv/AvelRen@4a8e010, deploy/postgres-privilege-gate.sh
та introspection-контракти app/tests/test_db_privileges.py. Новий CLI
не запускає Compose, pytest, migrate або прикладні SQL-функції.
"""

import hashlib
import json
import os
import sys
from pathlib import Path

import psycopg

ROLES = ("backup", "collector", "notifier", "watchdog", "api", "surge", "migrator")
TABLES = (
    "countries",
    "checkpoints",
    "observations",
    "observations_hourly",
    "collector_runs",
    "devices",
    "subscriptions",
    "subscription_state",
    "alerts",
    "eta_targets",
    "eta_alerts",
    "health_alerts",
    "notification_cancels",
    "schema_migrations",
    "admin_access",
    "surge_subscriptions",
    "surge_predictions",
    "surge_events",
    "surge_alerts",
    "surge_delivery_attempts",
    "surge_checkpoint_state",
)
SEQUENCES = (
    "alerts_id_seq",
    "eta_alerts_id_seq",
    "health_alerts_id_seq",
    "notification_cancels_id_seq",
    "subscriptions_id_seq",
    "eta_targets_id_seq",
    "surge_subscriptions_id_seq",
    "surge_predictions_id_seq",
    "surge_events_id_seq",
    "surge_alerts_id_seq",
    "surge_delivery_attempts_id_seq",
)
TABLE_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
COLUMN_PRIVILEGES = ("SELECT", "INSERT", "UPDATE", "REFERENCES")
SEQUENCE_PRIVILEGES = ("SELECT", "USAGE", "UPDATE")

# Expectations come from migration grants, never from the inspected ACL.
TABLE_ACL = {
    "backup": {name: {"SELECT"} for name in TABLES},
    "collector": {
        **{
            name: {"SELECT", "INSERT", "UPDATE"}
            for name in (
                "countries",
                "checkpoints",
                "observations",
                "collector_runs",
                "subscription_state",
                "alerts",
                "eta_targets",
                "eta_alerts",
            )
        },
        "subscriptions": {"SELECT"},
        "notification_cancels": {"INSERT"},
        "schema_migrations": {"SELECT"},
    },
    "notifier": {
        **{
            name: {"SELECT"}
            for name in (
                "alerts",
                "eta_alerts",
                "subscriptions",
                "eta_targets",
                "checkpoints",
                "schema_migrations",
                "surge_events",
            )
        },
        "notification_cancels": {"SELECT", "INSERT", "DELETE"},
        "surge_alerts": {"SELECT", "UPDATE"},
        "surge_delivery_attempts": {"SELECT", "INSERT", "UPDATE"},
    },
    "watchdog": {
        "observations": {"SELECT"},
        "collector_runs": {"SELECT"},
        "health_alerts": {"SELECT", "INSERT", "UPDATE"},
        "schema_migrations": {"SELECT"},
    },
    "api": {
        **{
            name: {"SELECT"}
            for name in (
                "countries",
                "checkpoints",
                "observations",
                "observations_hourly",
                "collector_runs",
                "alerts",
                "eta_alerts",
                "health_alerts",
                "schema_migrations",
                "admin_access",
                "surge_predictions",
                "surge_events",
            )
        },
        **{
            name: {"SELECT", "INSERT", "UPDATE", "DELETE"}
            for name in (
                "subscriptions",
                "eta_targets",
                "surge_subscriptions",
            )
        },
        "notification_cancels": {"INSERT"},
        "surge_alerts": {"SELECT", "INSERT", "UPDATE"},
    },
    "surge": {
        **{
            name: {"SELECT"}
            for name in (
                "observations",
                "checkpoints",
                "schema_migrations",
                "surge_subscriptions",
            )
        },
        **{
            name: {"SELECT", "INSERT", "UPDATE"}
            for name in (
                "surge_predictions",
                "surge_events",
                "surge_alerts",
                "surge_checkpoint_state",
            )
        },
        "notification_cancels": {"INSERT"},
    },
    "migrator": {name: set(TABLE_PRIVILEGES) for name in TABLES},
}
SEQUENCE_ACL = {
    "backup": {name: {"SELECT"} for name in SEQUENCES},
    "collector": {
        name: {"USAGE"}
        for name in (
            "alerts_id_seq",
            "eta_alerts_id_seq",
            "notification_cancels_id_seq",
        )
    },
    "notifier": {
        name: {"USAGE"}
        for name in (
            "notification_cancels_id_seq",
            "surge_delivery_attempts_id_seq",
        )
    },
    "watchdog": {"health_alerts_id_seq": {"USAGE"}},
    "api": {
        name: {"USAGE"}
        for name in (
            "subscriptions_id_seq",
            "eta_targets_id_seq",
            "notification_cancels_id_seq",
            "surge_subscriptions_id_seq",
            "surge_alerts_id_seq",
        )
    },
    "surge": {
        name: {"USAGE"}
        for name in (
            "surge_predictions_id_seq",
            "surge_events_id_seq",
            "surge_alerts_id_seq",
            "notification_cancels_id_seq",
        )
    },
    "migrator": {name: set(SEQUENCE_PRIVILEGES) for name in SEQUENCES},
}
COLUMN_ACL = {
    "collector": {"notification_cancels": {"kind": {"SELECT"}, "alert_id": {"SELECT"}}},
    "notifier": {
        "devices": {
            "id": {"SELECT"},
            "fcm_token": {"SELECT", "UPDATE"},
            "notification_capabilities": {"SELECT"},
        },
        **{
            name: {column: {"UPDATE"} for column in ("last_sent_at", "send_count")}
            for name in ("alerts", "eta_alerts")
        },
        "notification_cancels": {
            column: {"UPDATE"}
            for column in (
                "attempt_count",
                "last_attempt_at",
                "accepted_at",
                "abandoned_at",
            )
        },
    },
    "watchdog": {
        "devices": {"id": {"SELECT"}, "is_admin": {"SELECT"}, "fcm_token": {"SELECT", "UPDATE"}}
    },
    "api": {
        "devices": {
            "id": {"SELECT"},
            "fcm_token": {"SELECT", "INSERT", "UPDATE"},
            "platform": {"SELECT", "INSERT"},
            "secret_hash": {"SELECT", "INSERT"},
            "is_admin": {"SELECT"},
            "last_seen": {"SELECT", "UPDATE"},
            "admin_blocked_until": {"SELECT", "UPDATE"},
            "notification_capabilities": {"SELECT", "INSERT", "UPDATE"},
        },
        "admin_access": {"failures": {"UPDATE"}, "locked_until": {"UPDATE"}},
        **{
            name: {column: {"UPDATE"} for column in ("status", "acknowledged_at")}
            for name in ("alerts", "eta_alerts")
        },
        "notification_cancels": {"kind": {"SELECT"}, "alert_id": {"SELECT"}},
    },
    "surge": {
        "devices": {"id": {"SELECT"}, "notification_capabilities": {"SELECT"}},
        "notification_cancels": {"kind": {"SELECT"}, "alert_id": {"SELECT"}},
    },
}
FUNCTIONS = {
    "activate_approved_admin(uuid)": {"api", "migrator"},
    "prune_inactive_devices(boolean)": {"notifier", "migrator"},
    "activate_admin_after_pin(uuid)": {"api", "migrator"},
    "discard_disabled_surge_alert(bigint,uuid)": {"api", "surge", "migrator"},
}


def audit(conn, migrations: Path) -> list[str]:
    """Read catalog metadata only; return category names without credentials/data."""
    violations = set()
    if conn.execute("SHOW transaction_read_only").fetchone()[0] != "on":
        return ["read_only_required"]
    roles = conn.execute(
        """
        SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolreplication,
               rolbypassrls, rolinherit FROM pg_roles WHERE rolname=ANY(%s)
    """,
        ([f"avelren_{role}" for role in ROLES],),
    ).fetchall()
    if len(roles) != len(ROLES) or any(any(row[1:]) for row in roles):
        violations.add("role_capabilities")
    if len(roles) != len(ROLES):
        return sorted(violations)
    if conn.execute(
        """
        SELECT EXISTS(SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member
            JOIN pg_roles g ON g.oid=m.roleid
            WHERE r.rolname=ANY(%s) OR g.rolname=ANY(%s))
    """,
        ([f"avelren_{r}" for r in ROLES], [f"avelren_{r}" for r in ROLES]),
    ).fetchone()[0]:
        violations.add("role_memberships")

    relations = conn.execute("""
        SELECT c.oid, c.relname, c.relkind, pg_get_userbyid(c.relowner)
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relkind IN ('r','p','S','v','m','f')
    """).fetchall()
    actual_tables = {row[1] for row in relations if row[2] != "S"}
    actual_sequences = {row[1] for row in relations if row[2] == "S"}
    if actual_tables != set(TABLES) or actual_sequences != set(SEQUENCES):
        violations.add("relation_inventory")
    for oid, name, kind, owner in relations:
        if owner != "avelren_migrator":
            violations.add("relation_owner")
        if name not in (*TABLES, *SEQUENCES):
            continue
        privileges = SEQUENCE_PRIVILEGES if kind == "S" else TABLE_PRIVILEGES
        acl = SEQUENCE_ACL if kind == "S" else TABLE_ACL
        catalog_function = "has_sequence_privilege" if kind == "S" else "has_table_privilege"
        for role in ROLES:
            for privilege in privileges:
                actual = conn.execute(
                    f"SELECT {catalog_function}(%s, %s::oid, %s)",
                    (f"avelren_{role}", oid, privilege),
                ).fetchone()[0]
                if actual != (privilege in acl[role].get(name, set())):
                    violations.add("sequence_acl" if kind == "S" else "table_acl")
                grantable = conn.execute(
                    f"SELECT {catalog_function}(%s, %s::oid, %s)",
                    (f"avelren_{role}", oid, privilege + " WITH GRANT OPTION"),
                ).fetchone()[0]
                if grantable != (role == "migrator"):
                    violations.add("sequence_acl" if kind == "S" else "table_acl")
        if conn.execute(
            """
            SELECT EXISTS(SELECT 1 FROM pg_class c,
                LATERAL aclexplode(coalesce(c.relacl, acldefault(
                    CASE WHEN c.relkind='S' THEN 'S'::"char" ELSE 'r'::"char" END,
                    c.relowner))) a WHERE c.oid=%s AND a.grantee=0)
        """,
            (oid,),
        ).fetchone()[0]:
            violations.add("public_acl")
        if kind == "S":
            continue
        columns = conn.execute(
            """
            SELECT attnum, attname FROM pg_attribute
            WHERE attrelid=%s AND attnum>0 AND NOT attisdropped
        """,
            (oid,),
        ).fetchall()
        for number, column in columns:
            for role in ROLES:
                expected = acl[role].get(name, set()) | COLUMN_ACL.get(role, {}).get(name, {}).get(
                    column, set()
                )
                for privilege in COLUMN_PRIVILEGES:
                    actual = conn.execute(
                        "SELECT has_column_privilege(%s, %s::oid, %s::smallint, %s)",
                        (f"avelren_{role}", oid, number, privilege),
                    ).fetchone()[0]
                    if actual != (privilege in expected):
                        violations.add("column_acl")
                    grantable = conn.execute(
                        "SELECT has_column_privilege(%s, %s::oid, %s::smallint, %s)",
                        (f"avelren_{role}", oid, number, privilege + " WITH GRANT OPTION"),
                    ).fetchone()[0]
                    if grantable != (role == "migrator"):
                        violations.add("column_acl")
        if conn.execute(
            """
            SELECT EXISTS(SELECT 1 FROM pg_attribute c, LATERAL aclexplode(c.attacl) a
                WHERE c.attrelid=%s AND a.grantee=0)
        """,
            (oid,),
        ).fetchone()[0]:
            violations.add("public_acl")

    for role in ROLES:
        for privilege in ("USAGE", "CREATE"):
            actual = conn.execute(
                "SELECT has_schema_privilege(%s, 'public', %s)", (f"avelren_{role}", privilege)
            ).fetchone()[0]
            if actual != (privilege == "USAGE" or role == "migrator"):
                violations.add("schema_acl")
            if conn.execute(
                "SELECT has_schema_privilege(%s, 'public', %s)",
                (f"avelren_{role}", privilege + " WITH GRANT OPTION"),
            ).fetchone()[0]:
                violations.add("schema_acl")
        for privilege in ("CONNECT", "CREATE", "TEMP"):
            actual = conn.execute(
                "SELECT has_database_privilege(%s, current_database(), %s)",
                (f"avelren_{role}", privilege),
            ).fetchone()[0]
            if actual != (privilege == "CONNECT"):
                violations.add("database_acl")
            if conn.execute(
                "SELECT has_database_privilege(%s, current_database(), %s)",
                (f"avelren_{role}", privilege + " WITH GRANT OPTION"),
            ).fetchone()[0]:
                violations.add("database_acl")
    for query in (
        "SELECT EXISTS(SELECT 1 FROM pg_namespace n, LATERAL aclexplode(coalesce("
        "n.nspacl,acldefault('n',n.nspowner))) a WHERE n.nspname='public' AND a.grantee=0)",
        "SELECT EXISTS(SELECT 1 FROM pg_database d, LATERAL aclexplode(coalesce("
        "d.datacl,acldefault('d',d.datdba))) a WHERE d.datname=current_database() AND a.grantee=0)",
    ):
        if conn.execute(query).fetchone()[0]:
            violations.add("public_acl")

    functions = conn.execute("""
        SELECT p.oid, p.proname || '(' || replace(oidvectortypes(p.proargtypes),' ','') || ')',
               pg_get_userbyid(p.proowner), p.prosecdef, p.proconfig,
               EXISTS(SELECT 1 FROM aclexplode(coalesce(p.proacl,
                   acldefault('f',p.proowner))) a WHERE a.grantee=0)
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='public' AND NOT EXISTS(SELECT 1 FROM pg_depend d
            WHERE d.classid='pg_proc'::regclass AND d.objid=p.oid AND d.deptype='e')
    """).fetchall()
    if {row[1] for row in functions} != set(FUNCTIONS):
        violations.add("function_inventory")
    for oid, name, owner, definer, config, public in functions:
        if name not in FUNCTIONS:
            continue
        if (
            owner != "avelren_migrator"
            or not definer
            or config != ["search_path=pg_catalog, pg_temp"]
        ):
            violations.add("function_definition")
        if public:
            violations.add("function_acl")
        for role in ROLES:
            actual = conn.execute(
                "SELECT has_function_privilege(%s, %s::oid, 'EXECUTE')", (f"avelren_{role}", oid)
            ).fetchone()[0]
            if actual != (role in FUNCTIONS[name]):
                violations.add("function_acl")
            grantable = conn.execute(
                "SELECT has_function_privilege(%s, %s::oid, 'EXECUTE WITH GRANT OPTION')",
                (f"avelren_{role}", oid),
            ).fetchone()[0]
            if grantable != (role == "migrator"):
                violations.add("function_acl")

    # Global defaults replace PostgreSQL's defaults; per-schema defaults add
    # privileges. Missing global function/type rows must not hide PUBLIC access.
    if conn.execute("""
        SELECT EXISTS(
            SELECT 1 FROM pg_roles r CROSS JOIN (VALUES ('r'),('S'),('f'),('T')) kinds(kind),
                LATERAL aclexplode(coalesce((
                    SELECT d.defaclacl FROM pg_default_acl d
                    WHERE d.defaclrole=r.oid AND d.defaclnamespace=0
                      AND d.defaclobjtype=kinds.kind::"char"
                ), acldefault(kinds.kind::"char", r.oid))) a
            WHERE r.rolname='avelren_migrator' AND a.grantee<>r.oid
            UNION ALL
            SELECT 1 FROM pg_default_acl d JOIN pg_roles r ON r.oid=d.defaclrole,
                LATERAL aclexplode(d.defaclacl) a
            WHERE r.rolname='avelren_migrator' AND d.defaclnamespace<>0
              AND a.grantee<>r.oid
        )
    """).fetchone()[0]:
        violations.add("default_acl")

    if "schema_migrations" in actual_tables:
        expected = [
            (path.stem, hashlib.sha256(path.read_bytes()).hexdigest())
            for path in sorted(migrations.glob("*.sql"))
        ]
        actual = conn.execute(
            "SELECT version, sha256 FROM public.schema_migrations ORDER BY version"
        ).fetchall()
        if len(expected) != 16 or actual != expected:
            violations.add("migration_journal")
    else:
        violations.add("migration_journal")
    return sorted(violations)


def main() -> int:
    dsn = os.environ.get("AVELREN_PRIVILEGE_AUDIT_DSN")
    if not dsn or len(sys.argv) != 1:
        print("privilege gate: required audit DSN or invalid arguments", file=sys.stderr)
        return 2
    migrations = Path(__file__).resolve().parents[4] / "db/migrations"
    try:
        with psycopg.connect(
            dsn,
            connect_timeout=10,
            options="-c default_transaction_read_only=on -c statement_timeout=10000",
        ) as conn:
            violations = audit(conn, migrations)
            conn.rollback()
    except (psycopg.Error, OSError, ValueError):
        # libpq errors may contain DSN values or server-provided sensitive detail.
        print("privilege gate: audit unavailable", file=sys.stderr)
        return 2
    print(json.dumps({"status": "fail" if violations else "pass", "violations": violations}))
    return int(bool(violations))


if __name__ == "__main__":
    raise SystemExit(main())
