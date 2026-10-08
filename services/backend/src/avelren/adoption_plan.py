"""Explicit ownership/ACL plans; no migration replay or blanket reassignment."""

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from psycopg import sql

from . import privilege_gate as gate
from .adoption_inventory import AdoptionError, Snapshot, application_structure, decode, encode

MIGRATIONS = Path(__file__).resolve().parents[4] / "db/migrations"
OWNER = "avelren_migrator"
ALLOWED_ROLES = {f"avelren_{role}" for role in gate.ROLES} | {"avelren", "avelren_admin"}
SCHEMAS = {
    "public",
    "_timescaledb_cache",
    "_timescaledb_catalog",
    "_timescaledb_config",
    "_timescaledb_debug",
    "_timescaledb_functions",
    "_timescaledb_internal",
    "timescaledb_information",
    "timescaledb_experimental",
}


@dataclass(frozen=True)
class AdoptionPlan:
    format_version: int
    before: Snapshot
    expected: Snapshot
    forward: tuple[str, ...]
    inverse: tuple[str, ...]


def identifier(*parts):
    return sql.Identifier(*parts).as_string()


def _acl(owner, rights):
    return [
        {"grantor": owner, "grantee": role, "privilege": privilege, "grantable": False}
        for role, privileges in rights.items()
        for privilege in sorted(privileges)
    ]


def _check_acl(row):
    for entry in row["acl"]:
        if (
            set(entry) != {"grantor", "grantee", "privilege", "grantable"}
            or type(entry["grantable"]) is not bool
            or entry["grantee"] not in ALLOWED_ROLES | {"PUBLIC"}
            or entry["grantor"] != row["owner"]
        ):
            # Delegation chains require a separately proven grant-graph executor.
            raise AdoptionError("unsupported_grant_graph")


def _validate(snapshot):
    sections = snapshot.sections
    reference = json.loads((MIGRATIONS.parent / "security/adoption-016-contract.json").read_text())
    structural = Snapshot(1, snapshot.database, {**sections, **reference})
    if application_structure(snapshot) != application_structure(structural):
        raise AdoptionError("schema_definition")
    database = sections["database"]
    if (
        len(database) != 1
        or database[0]["identity"] != snapshot.database
        or database[0]["postgres_major"] != 16
        or {(r["name"], r["version"]) for r in database[0]["extensions"]}
        != {("timescaledb", "2.30.1"), ("plpgsql", "1.0")}
    ):
        raise AdoptionError("unsupported_database")
    expected_journal = {
        (path.stem, hashlib.sha256(path.read_bytes()).hexdigest())
        for path in MIGRATIONS.glob("*.sql")
    }
    if (
        len(expected_journal) != 16
        or len(sections["journal"]) != 16
        or {(r["version"], r["sha256"]) for r in sections["journal"]} != expected_journal
    ):
        raise AdoptionError("migration_journal")
    restricted = {f"avelren_{role}" for role in gate.ROLES}
    roles = {row["identity"]: row for row in sections["roles"]}
    if (
        not restricted <= roles.keys()
        or any(
            any(
                roles[role][attr]
                for attr in (
                    "superuser",
                    "createdb",
                    "createrole",
                    "replication",
                    "bypassrls",
                    "inherit",
                )
            )
            for role in restricted
        )
        or sections["memberships"]
    ):
        raise AdoptionError("role_capabilities")
    roots = [row for row in sections["relations"] if row["schema"] == "public"]
    if (
        {row["name"] for row in roots} != set(gate.TABLES) | set(gate.SEQUENCES)
        or len(roots) != len(gate.TABLES) + len(gate.SEQUENCES)
        or any(
            row["extension"] or row["owner"] not in ALLOWED_ROLES or row["rls"] or row["force_rls"]
            for row in roots
        )
    ):
        raise AdoptionError("relation_inventory")
    for row in roots:
        expected_kind = (
            "S"
            if row["name"] in gate.SEQUENCES
            else ("v" if row["name"] == "observations_hourly" else "r")
        )
        if row["kind"] != expected_kind:
            raise AdoptionError("relation_inventory")
    bodies = {}
    for path in sorted(MIGRATIONS.glob("*.sql")):
        for name, body in re.findall(
            r"CREATE(?: OR REPLACE)? FUNCTION (?:public\.)?(\w+)"
            r"\([^;]*?\bAS\s+\$\$(.*?)\$\$",
            path.read_text(),
            re.DOTALL | re.IGNORECASE,
        ):
            bodies[name] = body
    functions = [row for row in sections["routines"] if not row["extension"]]
    if {row["name"] + "(" + row["arguments"].replace(" ", "") + ")" for row in functions} != set(
        gate.FUNCTIONS
    ) or len(functions) != 4:
        raise AdoptionError("function_inventory")
    for row in functions:
        if (
            row["schema"] != "public"
            or row["owner"] not in ALLOWED_ROLES
            or not row["definer"]
            or row["config"] != ["search_path=pg_catalog, pg_temp"]
            or row["body"] != bodies.get(row["name"])
        ):
            raise AdoptionError("function_definition")
    for row in (
        *roots,
        *functions,
        database[0],
        *[r for r in sections["schemas"] if r["identity"] == "public"],
    ):
        _check_acl(row)
    relation_owners = {row["identity"]: row["owner"] for row in roots}
    for row in sections["columns"]:
        if row["relation"] in relation_owners:
            _check_acl({"owner": relation_owners[row["relation"]], "acl": row["acl"]})
    for row in sections["defaults"]:
        if row["owner"] == OWNER:
            if row["kind"] not in {"r", "S", "f", "T"}:
                raise AdoptionError("default_acl")
            _check_acl(row)
    # Extension-owned schemas/objects are classified, never accepted as application roots.
    if any(row["schema"] not in SCHEMAS for row in sections["relations"]) or any(
        row["identity"] not in SCHEMAS for row in sections["schemas"]
    ):
        raise AdoptionError("unsupported_topology")


def _target(before):
    after = copy.deepcopy(before)
    sections = after.sections
    changed = {}
    for row in sections["relations"]:
        if row["schema"] != "public":
            continue
        previous = row["owner"]
        row["owner"] = OWNER
        changed[row["identity"]] = OWNER
        rights = {
            OWNER: set(gate.SEQUENCE_PRIVILEGES if row["kind"] == "S" else gate.TABLE_PRIVILEGES)
        }
        mapping = gate.SEQUENCE_ACL if row["kind"] == "S" else gate.TABLE_ACL
        rights.update(
            {
                f"avelren_{role}": names[row["name"]]
                for role, names in mapping.items()
                if row["name"] in names
            }
        )
        row["acl"] = _acl(OWNER, rights)
        if previous == OWNER:
            # Track ownership propagation only when ALTER OWNER actually occurs.
            changed.pop(row["identity"])
    for row in sections["columns"]:
        if row["relation"].startswith("public."):
            name = row["relation"].removeprefix("public.")
            row["acl"] = _acl(
                OWNER,
                {
                    f"avelren_{role}": tables.get(name, {}).get(row["name"], set())
                    for role, tables in gate.COLUMN_ACL.items()
                },
            )
    for row in sections["routines"]:
        if row["extension"]:
            continue
        row["owner"] = OWNER
        name = row["name"] + "(" + row["arguments"].replace(" ", "") + ")"
        row["acl"] = _acl(OWNER, {f"avelren_{role}": {"EXECUTE"} for role in gate.FUNCTIONS[name]})
    for section, kind in (("database", "d"), ("schemas", "n")):
        for row in sections[section]:
            if kind == "n" and row["identity"] != "public":
                continue
            if row["owner"] not in {"avelren", "avelren_admin"}:
                raise AdoptionError("unsupported_owner")
            rights = {
                row["owner"]: {"CONNECT", "CREATE", "TEMPORARY"}
                if kind == "d"
                else {"USAGE", "CREATE"}
            }
            rights.update(
                {
                    f"avelren_{role}": {"CONNECT"}
                    if kind == "d"
                    else ({"USAGE", "CREATE"} if role == "migrator" else {"USAGE"})
                    for role in gate.ROLES
                }
            )
            row["acl"] = _acl(row["owner"], rights)
    kept = [r for r in sections["defaults"] if r["owner"] != OWNER]
    for kind, privileges in (
        ("r", gate.TABLE_PRIVILEGES),
        ("S", gate.SEQUENCE_PRIVILEGES),
        ("f", ("EXECUTE",)),
        ("T", ("USAGE",)),
    ):
        kept.append(
            {
                "owner": OWNER,
                "schema": "",
                "kind": kind,
                "acl": _acl(OWNER, {OWNER: set(privileges)}),
            }
        )
    sections["defaults"] = kept
    # Parent ownership changes include row types and indexes.
    for row in sections["dependencies"]:
        if row.get("parent") in changed:
            row["owner"] = OWNER
    return after


def _role(role):
    return "PUBLIC" if role == "PUBLIC" else identifier(role)


def _object(row, section):
    if section == "relations":
        kind = "SEQUENCE" if row["kind"] == "S" else "TABLE"
        return kind, identifier(row["schema"], row["name"])
    if section == "routines":
        arguments = row["arguments"]
        if arguments not in {"uuid", "boolean", "bigint, uuid"}:
            raise AdoptionError("function_arguments")
        return "FUNCTION", identifier(row["schema"], row["name"]) + "(" + arguments + ")"
    if section == "columns":
        return "TABLE", identifier("public", row["relation"].removeprefix("public."))
    return ("SCHEMA" if section == "schemas" else "DATABASE"), identifier(row["identity"])


def _replace_acl(start, end, section):
    kind, identity = _object(end, section)
    owner = end.get("owner", OWNER)
    roles = {entry["grantee"] for entry in start["acl"] + end["acl"]} | {"PUBLIC"}
    statements = ["SET ROLE " + identifier(owner)]
    column = " (" + identifier(end["name"]) + ")" if section == "columns" else ""
    statements.append(
        "REVOKE ALL PRIVILEGES"
        + column
        + " ON "
        + kind
        + " "
        + identity
        + " FROM "
        + ", ".join(_role(role) for role in sorted(roles))
        + " CASCADE"
    )
    for entry in end["acl"]:
        privilege = entry["privilege"]
        if privilege not in {
            *gate.TABLE_PRIVILEGES,
            *gate.SEQUENCE_PRIVILEGES,
            "EXECUTE",
            "CONNECT",
            "CREATE",
            "TEMPORARY",
            "USAGE",
        }:
            raise AdoptionError("acl_privilege")
        statements.append(
            "GRANT "
            + privilege
            + column
            + " ON "
            + kind
            + " "
            + identity
            + " TO "
            + _role(entry["grantee"])
            + (" WITH GRANT OPTION" if entry["grantable"] else "")
        )
    statements.append("RESET ROLE")
    return statements


def _defaults(start, end):
    result = []

    def key(row):
        return row["owner"], row["schema"], row["kind"]

    left = {key(row): row for row in start if row["owner"] == OWNER}
    right = {key(row): row for row in end if row["owner"] == OWNER}
    kinds = {"r": "TABLES", "S": "SEQUENCES", "f": "FUNCTIONS", "T": "TYPES"}
    for identity in sorted(left.keys() | right.keys()):
        before = left.get(identity, {"acl": []})
        after = right.get(identity, {"acl": []})
        if before["acl"] == after["acl"]:
            continue
        owner, schema, kind = identity
        prefix = "ALTER DEFAULT PRIVILEGES FOR ROLE " + identifier(owner)
        if schema:
            prefix += " IN SCHEMA " + identifier(schema)
        roles = {r["grantee"] for r in before["acl"] + after["acl"]} | {"PUBLIC"}
        result.append(
            prefix
            + " REVOKE ALL ON "
            + kinds[kind]
            + " FROM "
            + ", ".join(_role(role) for role in sorted(roles))
            + " CASCADE"
        )
        for entry in after["acl"]:
            result.append(
                prefix
                + " GRANT "
                + entry["privilege"]
                + " ON "
                + kinds[kind]
                + " TO "
                + _role(entry["grantee"])
                + (" WITH GRANT OPTION" if entry["grantable"] else "")
            )
    return result


def _statements(start, end):
    result = []
    for section in ("relations", "routines"):
        initial = {row["identity"]: row for row in start.sections[section]}
        for row in end.sections[section]:
            old = initial[row["identity"]]
            if old["owner"] != row["owner"]:
                kind, identity = _object(row, section)
                if section == "relations" and row["name"] == "observations_hourly":
                    kind = "MATERIALIZED VIEW"
                result.append(
                    "ALTER " + kind + " " + identity + " OWNER TO " + identifier(row["owner"])
                )
    for section in ("database", "schemas", "relations", "routines", "columns"):

        def identity(row, section=section):
            return (row["relation"] if section == "columns" else row["identity"]), row.get("name")

        initial = {identity(row): row for row in start.sections[section]}
        for row in end.sections[section]:
            old = initial[identity(row)]
            if old["acl"] != row["acl"] or old.get("owner") != row.get("owner"):
                target = row
                if section == "columns":
                    owners = {r["identity"]: r["owner"] for r in end.sections["relations"]}
                    target = {**row, "owner": owners[row["relation"]]}
                result.extend(_replace_acl(old, target, section))
    result.extend(_defaults(start.sections["defaults"], end.sections["defaults"]))
    return tuple(result)


def build_plan(snapshot: Snapshot) -> AdoptionPlan:
    try:
        _validate(snapshot)
        expected = _target(snapshot)
        # Canonicalize list order before comparing ACLs.
        before = decode(encode(snapshot))
        expected = decode(encode(expected))
        return AdoptionPlan(
            1, before, expected, _statements(before, expected), _statements(expected, before)
        )
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise AdoptionError("snapshot_contract") from exc


def encode_plan(plan: AdoptionPlan) -> bytes:
    return json.dumps(
        {
            "format_version": plan.format_version,
            "before": json.loads(encode(plan.before)),
            "expected": json.loads(encode(plan.expected)),
            "forward": list(plan.forward),
            "inverse": list(plan.inverse),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def plan_digest(plan: AdoptionPlan) -> str:
    return hashlib.sha256(encode_plan(plan)).hexdigest()


def decode_plan(payload: bytes) -> AdoptionPlan:
    try:
        value = json.loads(payload)
        if (
            not isinstance(value, dict)
            or set(value) != {"format_version", "before", "expected", "forward", "inverse"}
            or type(value["format_version"]) is not int
            or value["format_version"] != 1
        ):
            raise AdoptionError("plan_format")
        plan = build_plan(decode(json.dumps(value["before"]).encode()))
        if json.loads(encode_plan(plan)) != value:
            # SQL from a supplied plan is always re-generated, never trusted verbatim.
            raise AdoptionError("plan_contract")
        return plan
    except (ValueError, TypeError, KeyError) as exc:
        raise AdoptionError("plan_format") from exc
