"""Read-only PostgreSQL catalog inventory for adoption 001–016.

Behavioral provenance: AvelRen@4a8e010 deploy/postgres-ownership.lib.sh.
No table data, role passwords, migrations or service operations are read/run.
"""

import hashlib
import json
from dataclasses import dataclass

import psycopg
from psycopg.rows import dict_row

SECTIONS = (
    "database",
    "schemas",
    "relations",
    "columns",
    "routines",
    "defaults",
    "roles",
    "memberships",
    "dependencies",
    "topology",
    "shared",
    "journal",
)


class AdoptionError(Exception):
    """Stable category only: never include libpq messages or credentials."""

    def __init__(self, category: str):
        self.category = category
        super().__init__(category)


@dataclass(frozen=True)
class Snapshot:
    format_version: int
    database: str
    sections: dict[str, list[dict[str, object]]]


def _canonical(value):
    if isinstance(value, dict):
        return {key: _canonical(item) for key, item in sorted(value.items()) if key != "oid"}
    if isinstance(value, list):
        result = [_canonical(item) for item in value]
        if all(isinstance(item, dict) for item in result):
            result.sort(key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
        return result
    return value


def encode(snapshot: Snapshot) -> bytes:
    return json.dumps(
        _canonical(
            {
                "format_version": snapshot.format_version,
                "database": snapshot.database,
                "sections": snapshot.sections,
            }
        ),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def decode(payload: bytes) -> Snapshot:
    try:
        data = json.loads(payload)
        if (
            not isinstance(data, dict)
            or set(data) != {"format_version", "database", "sections"}
            or type(data["format_version"]) is not int
            or data["format_version"] != 1
            or not isinstance(data["database"], str)
            or not data["database"]
            or not isinstance(data["sections"], dict)
            or set(data["sections"]) != set(SECTIONS)
            or any(
                not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows)
                for rows in data["sections"].values()
            )
        ):
            raise AdoptionError("snapshot_format")
        return Snapshot(1, data["database"], data["sections"])
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise AdoptionError("snapshot_format") from exc


def fingerprint(snapshot: Snapshot) -> str:
    return hashlib.sha256(encode(snapshot)).hexdigest()


def application_structure(snapshot: Snapshot) -> dict:
    structure = {}
    for section in ("relations", "columns", "routines", "dependencies"):
        structure[section] = [
            {key: value for key, value in row.items() if key not in {"owner", "acl", "internal"}}
            for row in snapshot.sections[section]
            if not (row.get("kind") == "trigger" and row.get("internal"))
            and (
                row.get("schema") == "public"
                or row.get("relation", "").startswith("public.")
                or row.get("identity", "").startswith("public.")
                or row.get("kind") == "event_trigger"
            )
        ]
    return _canonical(structure)


def _acl(acl, owner, kind):
    # Arguments are fixed catalog expressions from this module, never input SQL.
    kind_sql = f"'{kind}'" if kind in ("r", "S", "d", "n", "c", "f", "T") else kind
    # pg_default_acl uses 'S'; acldefault uses lowercase 's' for sequences.
    kind_sql = f"CASE WHEN {kind_sql}='S' THEN 's' ELSE {kind_sql} END"
    return f"""(SELECT coalesce(jsonb_agg(jsonb_build_object(
        'grantor',pg_get_userbyid(a.grantor),
        'grantee',CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END,
        'privilege',a.privilege_type,'grantable',a.is_grantable)), '[]'::jsonb)
        FROM aclexplode(coalesce({acl},acldefault({kind_sql}::"char",{owner}))) a)"""


def capture(conn: psycopg.Connection) -> Snapshot:
    if conn.execute("SHOW transaction_read_only").fetchone()[0] != "on":
        raise AdoptionError("read_only_required")
    if conn.execute("SHOW transaction_isolation").fetchone()[0] != "repeatable read":
        raise AdoptionError("repeatable_read_required")
    return _capture_catalog(conn)


def _capture_catalog(conn: psycopg.Connection) -> Snapshot:
    """Only SELECTs; executor uses this inside its locked write transaction."""
    namespace = "n.nspname !~ '^pg_' AND n.nspname <> 'information_schema'"
    queries = {
        "database": f"""SELECT d.datname AS identity, pg_get_userbyid(d.datdba) AS owner,
            {_acl("d.datacl", "d.datdba", "d")} AS acl,
            current_setting('server_version_num')::int/10000 AS postgres_major,
            (SELECT jsonb_agg(jsonb_build_object('name',extname,'version',extversion,
                'owner',pg_get_userbyid(extowner))) FROM pg_extension) AS extensions
            FROM pg_database d WHERE d.datname=current_database()""",
        "schemas": f"""SELECT n.nspname AS identity, pg_get_userbyid(n.nspowner) AS owner,
            {_acl("n.nspacl", "n.nspowner", "n")} AS acl FROM pg_namespace n WHERE {namespace}""",
        "relations": f"""SELECT format('%I.%I',n.nspname,c.relname) AS identity,
            n.nspname AS schema,c.relname AS name,c.relkind AS kind,
            pg_get_userbyid(c.relowner) AS owner,
            {_acl("c.relacl", "c.relowner", "CASE WHEN c.relkind='S' THEN 'S' ELSE 'r' END")}
                AS acl,
            coalesce((SELECT e.extname FROM pg_depend d JOIN pg_extension e ON e.oid=d.refobjid
                WHERE d.classid='pg_class'::regclass AND d.objid=c.oid
                AND d.refclassid='pg_extension'::regclass AND d.deptype='e'),'') AS extension,
            c.relrowsecurity AS rls,c.relforcerowsecurity AS force_rls,c.reloptions AS options,
            CASE WHEN c.relkind IN ('v','m') THEN pg_get_viewdef(c.oid,true) END AS definition
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE {namespace} AND c.relkind IN ('r','p','v','m','S','f')""",
        "columns": f"""SELECT format('%I.%I',n.nspname,c.relname) AS relation,
            a.attname AS name,a.attnum AS position,format_type(a.atttypid,a.atttypmod) AS type,
            a.attnotnull AS not_null,a.attidentity AS identity,a.attgenerated AS generated,
            pg_get_expr(ad.adbin,ad.adrelid) AS default_expression,
            {_acl("a.attacl", "c.relowner", "c")} AS acl
            FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            LEFT JOIN pg_attrdef ad ON ad.adrelid=c.oid AND ad.adnum=a.attnum
            WHERE {namespace} AND a.attnum>0 AND NOT a.attisdropped
                AND c.relkind IN ('r','p','v','m','S','f')""",
        "routines": f"""SELECT format('%I.%I(%s)',n.nspname,p.proname,
            oidvectortypes(p.proargtypes)) AS identity,n.nspname AS schema,
            p.proname AS name,oidvectortypes(p.proargtypes) AS arguments,
            pg_get_userbyid(p.proowner) AS owner,p.prosecdef AS definer,p.proconfig AS config,
            pg_get_functiondef(p.oid) AS definition,p.prosrc AS body,
            {_acl("p.proacl", "p.proowner", "f")} AS acl,
            coalesce((SELECT e.extname FROM pg_depend d JOIN pg_extension e ON e.oid=d.refobjid
                WHERE d.classid='pg_proc'::regclass AND d.objid=p.oid
                AND d.refclassid='pg_extension'::regclass AND d.deptype='e'),'') AS extension
            FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE {namespace} AND p.prokind IN ('f','p')""",
        "defaults": f"""SELECT r.rolname AS owner,'' AS schema,k.kind AS kind,
            {_acl("d.defaclacl", "r.oid", "k.kind")} AS acl
            FROM pg_roles r CROSS JOIN (VALUES ('r'),('S'),('f'),('T')) k(kind)
            LEFT JOIN pg_default_acl d ON d.defaclrole=r.oid AND d.defaclnamespace=0
                AND d.defaclobjtype=k.kind::"char"
            WHERE r.rolname LIKE 'avelren%'
            UNION ALL SELECT pg_get_userbyid(d.defaclrole),n.nspname,d.defaclobjtype::text,
            (SELECT coalesce(jsonb_agg(jsonb_build_object('grantor',pg_get_userbyid(a.grantor),
            'grantee',CASE WHEN a.grantee=0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END,
            'privilege',a.privilege_type,'grantable',a.is_grantable)),'[]'::jsonb)
            FROM aclexplode(d.defaclacl) a) FROM pg_default_acl d
            JOIN pg_namespace n ON n.oid=d.defaclnamespace""",
        "roles": """SELECT rolname AS identity,rolsuper AS superuser,rolcreatedb AS createdb,
            rolcreaterole AS createrole,rolreplication AS replication,rolbypassrls AS bypassrls,
            rolinherit AS inherit,rolcanlogin AS login,rolconnlimit AS connection_limit,
            rolvaliduntil::text AS valid_until,rolconfig AS config FROM pg_roles
            WHERE rolname LIKE 'avelren%'""",
        "memberships": """SELECT pg_get_userbyid(roleid) AS role,
            pg_get_userbyid(member) AS member,pg_get_userbyid(grantor) AS grantor,
            admin_option,inherit_option,set_option FROM pg_auth_members
            WHERE pg_get_userbyid(roleid) LIKE 'avelren%'
               OR pg_get_userbyid(member) LIKE 'avelren%'""",
        "dependencies": f"""SELECT format('%I.%I',n.nspname,c.relname) AS identity,
            c.relkind::text AS kind,pg_get_indexdef(c.oid) AS definition,
            pg_get_userbyid(c.relowner) AS owner,
            (SELECT format('%I.%I',pn.nspname,p.relname) FROM pg_index ix
                JOIN pg_class p ON p.oid=ix.indrelid
                JOIN pg_namespace pn ON pn.oid=p.relnamespace
                WHERE ix.indexrelid=c.oid) AS parent,false AS internal,NULL::text AS enabled
            FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE {namespace} AND c.relkind IN ('i','I')
            UNION ALL SELECT format('%I.%I.%I',n.nspname,c.relname,
                CASE WHEN t.tgisinternal THEN regexp_replace(t.tgname,'_[0-9]+$','_OID')
                    ELSE t.tgname END),
            'trigger',CASE WHEN t.tgisinternal THEN replace(pg_get_triggerdef(t.oid,true),
                t.tgname,regexp_replace(t.tgname,'_[0-9]+$','_OID'))
                ELSE pg_get_triggerdef(t.oid,true) END,pg_get_userbyid(c.relowner),
            format('%I.%I',n.nspname,c.relname),t.tgisinternal,t.tgenabled::text FROM pg_trigger t
            JOIN pg_class c ON c.oid=t.tgrelid JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE {namespace}
            UNION ALL SELECT format('%I.%I.%I',n.nspname,c.relname,p.polname),'policy',
            jsonb_build_object('command',p.polcmd,'permissive',p.polpermissive,
                'roles',(SELECT array_agg(CASE WHEN r=0 THEN 'PUBLIC'
                     ELSE pg_get_userbyid(r) END) FROM unnest(p.polroles) r),
                'using',pg_get_expr(p.polqual,p.polrelid),
                'check',pg_get_expr(p.polwithcheck,p.polrelid))::text,
                pg_get_userbyid(c.relowner),format('%I.%I',n.nspname,c.relname),false,NULL
            FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace WHERE {namespace}
            UNION ALL SELECT format('%I.%I',n.nspname,t.typname),'type',
                jsonb_build_object('kind',t.typtype,'base',format_type(t.typbasetype,NULL),
                    'not_null',t.typnotnull,'default',t.typdefault)::text,
                pg_get_userbyid(t.typowner),
                CASE WHEN c.oid IS NOT NULL THEN format('%I.%I',cn.nspname,c.relname)
                    WHEN element.oid IS NOT NULL THEN format('%I.%I',en.nspname,element.typname)
                END,false,NULL
            FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
            LEFT JOIN pg_class c ON c.oid=t.typrelid
            LEFT JOIN pg_namespace cn ON cn.oid=c.relnamespace
            LEFT JOIN pg_type element ON element.oid=t.typelem
            LEFT JOIN pg_namespace en ON en.oid=element.typnamespace WHERE {namespace}
            UNION ALL SELECT format('%I.%I.%I',n.nspname,c.relname,k.conname),'constraint',
                pg_get_constraintdef(k.oid,true),pg_get_userbyid(c.relowner),
                format('%I.%I',n.nspname,c.relname),false,NULL
            FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace WHERE {namespace}
            UNION ALL SELECT 'event_trigger.' || e.evtname,'event_trigger',
                jsonb_build_object('event',e.evtevent,'enabled',e.evtenabled,
                    'function',e.evtfoid::regprocedure::text,'tags',e.evttags)::text,
                pg_get_userbyid(e.evtowner),NULL,false,e.evtenabled::text
                FROM pg_event_trigger e""",
        "topology": """SELECT 'hypertable' AS kind,format('%I.%I',h.schema_name,h.table_name)
            AS identity,h.compression_state AS compression,
            CASE WHEN z.id IS NOT NULL THEN format('%I.%I',z.schema_name,z.table_name)
                END AS related
            FROM _timescaledb_catalog.hypertable h
            LEFT JOIN _timescaledb_catalog.hypertable z ON z.id=h.compressed_hypertable_id
            UNION ALL SELECT 'chunk',format('%I.%I',n.nspname,r.relname),c.status,
                format('%I.%I',h.schema_name,h.table_name)
            FROM _timescaledb_catalog.chunk c
            JOIN pg_class r ON r.oid=c.relid JOIN pg_namespace n ON n.oid=r.relnamespace
            JOIN _timescaledb_catalog.hypertable h ON h.id=c.hypertable_id
            UNION ALL SELECT 'continuous_aggregate',
                format('%I.%I',c.user_view_schema,c.user_view_name),
                NULL,format('%I.%I',h.schema_name,h.table_name)
            FROM _timescaledb_catalog.continuous_agg c
            JOIN _timescaledb_catalog.hypertable h ON h.id=c.mat_hypertable_id
            UNION ALL SELECT 'aggregate_part',format('%I.%I',c.partial_view_schema,
                c.partial_view_name),NULL,format('%I.%I',c.user_view_schema,c.user_view_name)
            FROM _timescaledb_catalog.continuous_agg c
            UNION ALL SELECT 'aggregate_part',format('%I.%I',c.direct_view_schema,
                c.direct_view_name),NULL,format('%I.%I',c.user_view_schema,c.user_view_name)
            FROM _timescaledb_catalog.continuous_agg c
            UNION ALL SELECT 'compressed_relation',format('%I.%I',cn.nspname,z.relname),
                NULL,format('%I.%I',n.nspname,r.relname)
            FROM _timescaledb_catalog.compression_settings s
            JOIN pg_class r ON r.oid=s.relid JOIN pg_namespace n ON n.oid=r.relnamespace
            JOIN pg_class z ON z.oid=s.compress_relid
            JOIN pg_namespace cn ON cn.oid=z.relnamespace""",
        "shared": """SELECT d.datname AS database,pg_get_userbyid(s.refobjid) AS role,
            s.classid::regclass::text AS kind,count(*) AS objects
            FROM pg_shdepend s JOIN pg_database d ON d.oid=s.dbid
            WHERE d.datname<>current_database() AND s.refclassid='pg_authid'::regclass
              AND pg_get_userbyid(s.refobjid) LIKE 'avelren%'
            GROUP BY d.datname,s.refobjid,s.classid""",
        "journal": "SELECT version,sha256,applied_at::text FROM public.schema_migrations",
    }
    sections = {}
    with conn.cursor(row_factory=dict_row) as cursor:
        for name, query in queries.items():
            cursor.execute(query)
            sections[name] = cursor.fetchall()
    database = sections["database"][0]["identity"]
    return Snapshot(1, database, _canonical(sections))
