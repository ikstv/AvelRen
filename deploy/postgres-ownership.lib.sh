#!/usr/bin/env bash
# Source-only catalog/ownership planning library for PostgreSQL adoption.

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo 'postgres ownership library is source-only' >&2
    exit 2
fi

readonly AVELREN_LEGACY_ROLE=avelren
readonly AVELREN_ADMIN_ROLE=avelren_admin
readonly AVELREN_MIGRATOR_ROLE=avelren_migrator

ownership_fail() {
    echo "postgres ownership preflight failed: $*" >&2
    return 1
}

prepare_evidence_dir() {
    local directory=$1
    [ ! -L "$directory" ] || ownership_fail 'evidence directory must not be a symlink'
    mkdir -p "$directory"
    chmod 700 "$directory"
    [ "$(stat -c '%a' "$directory")" = 700 ] || ownership_fail 'evidence directory mode must be 0700'
    [ "$(stat -c '%u' "$directory")" = "$(id -u)" ] || ownership_fail 'evidence directory owner mismatch'
}

_evidence_temp() {
    local target=$1 directory
    directory=$(dirname "$target")
    prepare_evidence_dir "$directory"
    mktemp "$directory/.ownership.XXXXXX"
}

_publish_evidence_file() {
    local temporary=$1 target=$2
    chmod 600 "$temporary"
    mv -f "$temporary" "$target"
    chmod 600 "$target"
}

_adoption_psql() {
    local dsn=$1
    shift
    PGDATABASE="$dsn" "${AVELREN_PSQL_BIN:-psql}" -X -qAt -v ON_ERROR_STOP=1 "$@"
}

_manifest_sql() {
    cat <<'SQL'
WITH RECURSIVE
canonical_roles(role_name) AS (
    VALUES ('avelren'), ('avelren_admin'), ('avelren_migrator')
),
target_database AS (
    SELECT database.oid, database.datname, database.datdba, database.datacl,
           pg_get_userbyid(database.datdba) AS owner_name,
           format('%I', database.datname) AS identity
    FROM pg_database AS database
    WHERE database.datname = current_database()
),
database_inventory AS (
    SELECT database.oid, database.datname,
           pg_get_userbyid(database.datdba) AS owner_name,
           format('%I', database.datname) AS identity,
           CASE WHEN database.datname = current_database() THEN 'application' ELSE 'shared' END AS source
    FROM pg_database AS database
    WHERE pg_get_userbyid(database.datdba) IN (SELECT role_name FROM canonical_roles)
),
namespace_base AS (
    SELECT namespace.oid, namespace.nspname, namespace.nspowner, namespace.nspacl,
           pg_get_userbyid(namespace.nspowner) AS owner_name,
           format('%I', namespace.nspname) AS identity,
           CASE
             WHEN namespace.nspname LIKE '\_timescaledb\_%' ESCAPE '\'
               OR EXISTS (
                   SELECT 1 FROM pg_depend AS dependency
                   JOIN pg_extension AS extension ON extension.oid = dependency.refobjid
                   WHERE dependency.classid = 'pg_namespace'::regclass
                     AND dependency.objid = namespace.oid
                     AND dependency.refclassid = 'pg_extension'::regclass
                     AND dependency.deptype = 'e'
                     AND extension.extname = 'timescaledb'
               ) THEN 'timescale'
             ELSE 'application'
           END AS source
    FROM pg_namespace AS namespace
    WHERE namespace.nspname = 'public'
       OR namespace.nspname LIKE '\_timescaledb\_%' ESCAPE '\'
       OR pg_get_userbyid(namespace.nspowner) IN (SELECT role_name FROM canonical_roles)
),
extension_base AS (
    SELECT extension.oid, extension.extname, extension.extowner,
           pg_get_userbyid(extension.extowner) AS owner_name,
           format('%I', extension.extname) AS identity,
           CASE WHEN extension.extname = 'timescaledb' THEN 'timescale' ELSE 'extension' END AS source
    FROM pg_extension AS extension
    WHERE extension.extname = 'timescaledb'
       OR pg_get_userbyid(extension.extowner) IN (SELECT role_name FROM canonical_roles)
),
timescale_hypertable_base AS (
    SELECT hypertable.hypertable_schema AS nspname,
           hypertable.hypertable_name AS relname,
           hypertable.owner::text AS owner_name,
           format('%I.%I', hypertable.hypertable_schema, hypertable.hypertable_name) AS identity
    FROM timescaledb_information.hypertables AS hypertable
    WHERE hypertable.hypertable_schema = 'public'
),
timescale_continuous_aggregate_base AS (
    SELECT aggregate.view_schema AS nspname,
           aggregate.view_name AS relname,
           aggregate.view_owner::text AS owner_name,
           format('%I.%I', aggregate.view_schema, aggregate.view_name) AS identity
    FROM timescaledb_information.continuous_aggregates AS aggregate
    WHERE aggregate.view_schema = 'public'
),
relation_base AS (
    SELECT relation.oid, namespace.nspname, relation.relname, relation.relkind,
           relation.relowner, relation.relacl,
           pg_get_userbyid(relation.relowner) AS owner_name,
           format('%I.%I', namespace.nspname, relation.relname) AS identity,
           CASE
             WHEN namespace.nspname LIKE '\_timescaledb\_%' ESCAPE '\'
               OR EXISTS (
                   SELECT 1
                   FROM pg_depend AS dependency
                   JOIN pg_extension AS extension ON extension.oid = dependency.refobjid
                   WHERE dependency.classid = 'pg_class'::regclass
                     AND dependency.objid = relation.oid
                     AND dependency.refclassid = 'pg_extension'::regclass
                     AND dependency.deptype = 'e'
                     AND extension.extname = 'timescaledb'
               ) THEN 'timescale'
             ELSE 'application'
           END AS source
    FROM pg_class AS relation
    JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    WHERE relation.relkind IN ('r', 'p', 'S', 'v', 'm')
      AND (
          namespace.nspname = 'public'
          OR namespace.nspname LIKE '\_timescaledb\_%' ESCAPE '\'
          OR pg_get_userbyid(namespace.nspowner) IN (SELECT role_name FROM canonical_roles)
          OR pg_get_userbyid(relation.relowner) IN (SELECT role_name FROM canonical_roles)
          OR EXISTS (
              SELECT 1
              FROM pg_depend AS dependency
              JOIN pg_extension AS extension ON extension.oid = dependency.refobjid
              WHERE dependency.classid = 'pg_class'::regclass
                AND dependency.objid = relation.oid
                AND dependency.refclassid = 'pg_extension'::regclass
                AND dependency.deptype = 'e'
                AND extension.extname = 'timescaledb'
          )
      )
),
routine_base AS (
    SELECT routine.oid, namespace.nspname, routine.proname, routine.prokind,
           routine.proowner, routine.proacl,
           pg_get_userbyid(routine.proowner) AS owner_name,
           format('%I.%I(%s)', namespace.nspname, routine.proname,
                  pg_get_function_identity_arguments(routine.oid)) AS identity,
           CASE
             WHEN namespace.nspname LIKE '\_timescaledb\_%' ESCAPE '\'
               OR EXISTS (
                   SELECT 1
                   FROM pg_depend AS dependency
                   JOIN pg_extension AS extension ON extension.oid = dependency.refobjid
                   WHERE dependency.classid = 'pg_proc'::regclass
                     AND dependency.objid = routine.oid
                     AND dependency.refclassid = 'pg_extension'::regclass
                     AND dependency.deptype = 'e'
                     AND extension.extname = 'timescaledb'
               ) THEN 'timescale'
             ELSE 'application'
           END AS source
    FROM pg_proc AS routine
    JOIN pg_namespace AS namespace ON namespace.oid = routine.pronamespace
    WHERE namespace.nspname = 'public'
       OR namespace.nspname LIKE '\_timescaledb\_%' ESCAPE '\'
       OR pg_get_userbyid(namespace.nspowner) IN (SELECT role_name FROM canonical_roles)
       OR pg_get_userbyid(routine.proowner) IN (SELECT role_name FROM canonical_roles)
       OR EXISTS (
           SELECT 1
           FROM pg_depend AS dependency
           JOIN pg_extension AS extension ON extension.oid = dependency.refobjid
           WHERE dependency.classid = 'pg_proc'::regclass
             AND dependency.objid = routine.oid
             AND dependency.refclassid = 'pg_extension'::regclass
             AND dependency.deptype = 'e'
             AND extension.extname = 'timescaledb'
       )
),
type_base AS (
    SELECT type.oid, namespace.nspname, type.typname, type.typtype,
           type.typowner, type.typacl,
           pg_get_userbyid(type.typowner) AS owner_name,
           format('%I.%I', namespace.nspname, type.typname) AS identity,
           CASE
             WHEN namespace.nspname LIKE '\_timescaledb\_%' ESCAPE '\'
               OR EXISTS (
                   SELECT 1
                   FROM pg_depend AS dependency
                   JOIN pg_extension AS extension ON extension.oid = dependency.refobjid
                   WHERE dependency.classid = 'pg_type'::regclass
                     AND dependency.objid = type.oid
                     AND dependency.refclassid = 'pg_extension'::regclass
                     AND dependency.deptype = 'e'
                     AND extension.extname = 'timescaledb'
               ) THEN 'timescale'
             ELSE 'application'
           END AS source
    FROM pg_type AS type
    JOIN pg_namespace AS namespace ON namespace.oid = type.typnamespace
    WHERE type.typrelid = 0
      AND type.typtype IN ('d', 'e', 'm', 'r')
      AND (
          namespace.nspname = 'public'
          OR namespace.nspname LIKE '\_timescaledb\_%' ESCAPE '\'
          OR pg_get_userbyid(namespace.nspowner) IN (SELECT role_name FROM canonical_roles)
          OR pg_get_userbyid(type.typowner) IN (SELECT role_name FROM canonical_roles)
          OR EXISTS (
              SELECT 1
              FROM pg_depend AS dependency
              JOIN pg_extension AS extension ON extension.oid = dependency.refobjid
              WHERE dependency.classid = 'pg_type'::regclass
                AND dependency.objid = type.oid
                AND dependency.refclassid = 'pg_extension'::regclass
                AND dependency.deptype = 'e'
                AND extension.extname = 'timescaledb'
          )
      )
),
manifest_rows AS (
    SELECT ARRAY['object','database',datname,'-',datname,'database',owner_name,'-','-','-','-','-',source,identity]::text[] AS fields
    FROM database_inventory
    UNION ALL
    SELECT ARRAY['object','schema',current_database(),nspname,nspname,'schema',owner_name,'-','-','-','-','-',source,identity]::text[]
    FROM namespace_base
    UNION ALL
    SELECT ARRAY['object','extension',current_database(),'-',extname,'extension',owner_name,'-','-','-','-','-',source,identity]::text[]
    FROM extension_base
    UNION ALL
    SELECT ARRAY['object','timescale_binding',current_database(),nspname,relname,'hypertable',owner_name,'-','-','-','-','-','timescale',identity]::text[]
    FROM timescale_hypertable_base
    UNION ALL
    SELECT ARRAY['object','timescale_binding',current_database(),nspname,relname,'continuous_aggregate',owner_name,'-','-','-','-','-','timescale',identity]::text[]
    FROM timescale_continuous_aggregate_base
    UNION ALL
    SELECT ARRAY['object','relation',current_database(),nspname,relname,relkind::text,owner_name,'-','-','-','-','-',source,identity]::text[]
    FROM relation_base
    UNION ALL
    SELECT ARRAY['object','column',current_database(),relation.nspname,relation.relname,relation.relkind::text,
                 relation.owner_name,attribute.attname,'-','-','-','-',relation.source,relation.identity]::text[]
    FROM relation_base AS relation
    JOIN pg_attribute AS attribute ON attribute.attrelid = relation.oid
    WHERE attribute.attnum > 0 AND NOT attribute.attisdropped
    UNION ALL
    SELECT ARRAY['object','function',current_database(),nspname,proname,prokind::text,owner_name,'-','-','-','-','-',source,identity]::text[]
    FROM routine_base
    UNION ALL
    SELECT ARRAY['object','type',current_database(),nspname,typname,typtype::text,owner_name,'-','-','-','-','-',source,identity]::text[]
    FROM type_base
    UNION ALL
    SELECT ARRAY['object','tablespace','-', '-', tablespace.spcname,'tablespace',
                 pg_get_userbyid(tablespace.spcowner),'-','-','-','-','-','shared',format('%I', tablespace.spcname)]::text[]
    FROM pg_tablespace AS tablespace
    WHERE pg_get_userbyid(tablespace.spcowner) IN (SELECT role_name FROM canonical_roles)
    UNION ALL
    SELECT ARRAY['object','default_acl',current_database(),COALESCE(namespace.nspname, '-'),
                 default_acl.oid::text,default_acl.defaclobjtype::text,pg_get_userbyid(default_acl.defaclrole),
                 '-','-','-','-','-','application',
                 format('%s:%s:%s', default_acl.defaclrole, default_acl.defaclnamespace, default_acl.defaclobjtype)]::text[]
    FROM pg_default_acl AS default_acl
    LEFT JOIN pg_namespace AS namespace ON namespace.oid = default_acl.defaclnamespace
    WHERE pg_get_userbyid(default_acl.defaclrole) IN (SELECT role_name FROM canonical_roles)
      AND (default_acl.defaclnamespace = 0 OR namespace.nspname = 'public')
    UNION ALL
    SELECT ARRAY['object','shared',shared.dbid::text,'-',shared.objid::text,shared.classid::regclass::text,
                 pg_get_userbyid(shared.refobjid),'-','-','-','-','-','shared',
                 format('%s:%s:%s', shared.dbid, shared.classid, shared.objid)]::text[]
    FROM pg_shdepend AS shared
    JOIN pg_roles AS owner_role ON owner_role.oid = shared.refobjid
    WHERE shared.refclassid = 'pg_authid'::regclass
      AND shared.deptype = 'o'
      AND owner_role.rolname IN (SELECT role_name FROM canonical_roles)
      AND shared.dbid <> (SELECT oid FROM target_database)
      AND shared.classid NOT IN ('pg_database'::regclass, 'pg_tablespace'::regclass)
    UNION ALL
    SELECT ARRAY['object',
                 CASE WHEN extension.oid IS NULL THEN 'shared' ELSE 'extension_dependent' END,
                 shared.dbid::text,'-',shared.objid::text,shared.classid::regclass::text,
                 pg_get_userbyid(shared.refobjid),'-','-','-','-','-',
                 CASE WHEN extension.oid IS NULL THEN 'shared' ELSE 'timescale' END,
                 format('%s:%s:%s', shared.dbid, shared.classid, shared.objid)]::text[]
    FROM pg_shdepend AS shared
    JOIN pg_roles AS owner_role ON owner_role.oid = shared.refobjid
    LEFT JOIN pg_depend AS dependency
      ON dependency.classid = shared.classid
     AND dependency.objid = shared.objid
     AND dependency.refclassid = 'pg_extension'::regclass
     AND dependency.deptype = 'e'
    LEFT JOIN pg_extension AS extension
      ON extension.oid = dependency.refobjid
     AND extension.extname = 'timescaledb'
    WHERE shared.refclassid = 'pg_authid'::regclass
      AND shared.deptype = 'o'
      AND owner_role.rolname IN (SELECT role_name FROM canonical_roles)
      AND shared.dbid = (SELECT oid FROM target_database)
      AND shared.classid NOT IN (
          'pg_namespace'::regclass, 'pg_class'::regclass, 'pg_proc'::regclass,
          'pg_type'::regclass, 'pg_extension'::regclass, 'pg_default_acl'::regclass
      )
    UNION ALL
    SELECT ARRAY['acl','database',database.datname,'-',database.datname,'database',database.owner_name,'object',
                 pg_get_userbyid(acl.grantor),CASE WHEN acl.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(acl.grantee) END,
                 acl.privilege_type,acl.is_grantable::text,'application',database.identity]::text[]
    FROM target_database AS database
    CROSS JOIN LATERAL aclexplode(COALESCE(database.datacl, acldefault('d', database.datdba))) AS acl
    UNION ALL
    SELECT ARRAY['acl','schema',current_database(),namespace.nspname,namespace.nspname,'schema',namespace.owner_name,'object',
                 pg_get_userbyid(acl.grantor),CASE WHEN acl.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(acl.grantee) END,
                 acl.privilege_type,acl.is_grantable::text,namespace.source,namespace.identity]::text[]
    FROM namespace_base AS namespace
    CROSS JOIN LATERAL aclexplode(COALESCE(namespace.nspacl, acldefault('n', namespace.nspowner))) AS acl
    UNION ALL
    SELECT ARRAY['acl','relation',current_database(),relation.nspname,relation.relname,relation.relkind::text,
                 relation.owner_name,'object',pg_get_userbyid(acl.grantor),
                 CASE WHEN acl.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(acl.grantee) END,
                 acl.privilege_type,acl.is_grantable::text,relation.source,relation.identity]::text[]
    FROM relation_base AS relation
    CROSS JOIN LATERAL aclexplode(COALESCE(
        relation.relacl,
        acldefault(CASE WHEN relation.relkind = 'S' THEN 's' ELSE 'r' END::"char", relation.relowner)
    )) AS acl
    UNION ALL
    SELECT ARRAY['acl','relation',current_database(),relation.nspname,relation.relname,relation.relkind::text,
                 relation.owner_name,attribute.attname,pg_get_userbyid(acl.grantor),
                 CASE WHEN acl.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(acl.grantee) END,
                 acl.privilege_type,acl.is_grantable::text,relation.source,relation.identity]::text[]
    FROM relation_base AS relation
    JOIN pg_attribute AS attribute ON attribute.attrelid = relation.oid
    CROSS JOIN LATERAL aclexplode(attribute.attacl) AS acl
    WHERE attribute.attnum > 0 AND NOT attribute.attisdropped AND attribute.attacl IS NOT NULL
    UNION ALL
    SELECT ARRAY['acl','function',current_database(),routine.nspname,routine.proname,routine.prokind::text,
                 routine.owner_name,'object',pg_get_userbyid(acl.grantor),
                 CASE WHEN acl.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(acl.grantee) END,
                 acl.privilege_type,acl.is_grantable::text,routine.source,routine.identity]::text[]
    FROM routine_base AS routine
    CROSS JOIN LATERAL aclexplode(COALESCE(routine.proacl, acldefault('f', routine.proowner))) AS acl
    UNION ALL
    SELECT ARRAY['acl','type',current_database(),type.nspname,type.typname,type.typtype::text,
                 type.owner_name,'object',pg_get_userbyid(acl.grantor),
                 CASE WHEN acl.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(acl.grantee) END,
                 acl.privilege_type,acl.is_grantable::text,type.source,type.identity]::text[]
    FROM type_base AS type
    CROSS JOIN LATERAL aclexplode(COALESCE(type.typacl, acldefault('T', type.typowner))) AS acl
)
SELECT array_to_string(fields, chr(9))
FROM manifest_rows
ORDER BY array_to_string(fields, chr(9)) COLLATE "C";
SQL
}

_normalize_manifest() {
    local input=$1 output=$2
    awk -F '\t' '
        NF != 14 { bad=1; next }
        $1 != "object" && $1 != "acl" { bad=1; next }
        $13 == "system" { next }
        $13 != "application" && $13 != "timescale" && $13 != "extension" && $13 != "shared" { bad=1; next }
        { print }
        END { if (bad) exit 1 }
    ' "$input" | LC_ALL=C sort >"$output"
}

capture_manifest() {
    local dsn=$1 output=$2 raw temporary
    temporary=$(_evidence_temp "$output")
    raw=$(_evidence_temp "$output")
    if [ -n "${AVELREN_CATALOG_FIXTURE_DIR:-}" ]; then
        local category file
        for category in database schema extension relations sequences routines timescale shared acl system; do
            file="$AVELREN_CATALOG_FIXTURE_DIR/$category.tsv"
            [ -f "$file" ] && cat "$file"
        done >"$raw"
    else
        _manifest_sql | _adoption_psql "$dsn" >"$raw"
    fi
    if ! _normalize_manifest "$raw" "$temporary"; then
        rm -f "$raw" "$temporary"
        ownership_fail 'catalog manifest was malformed'
        return 1
    fi
    rm -f "$raw"
    [ -s "$temporary" ] || {
        rm -f "$temporary"
        ownership_fail 'catalog manifest was empty'
        return 1
    }
    _publish_evidence_file "$temporary" "$output"
}

manifest_fingerprint() {
    local manifest=$1
    sha256sum "$manifest" | awk '{print $1}'
}

_canonical_relations() {
    cat <<'EOF'
public	alerts	r
public	alerts_id_seq	S
public	checkpoints	r
public	collector_runs	r
public	countries	r
public	devices	r
public	eta_alerts	r
public	eta_alerts_id_seq	S
public	eta_targets	r
public	eta_targets_id_seq	S
public	health_alerts	r
public	health_alerts_id_seq	S
public	notification_cancels	r
public	notification_cancels_id_seq	S
public	observations	r
public	observations_hourly	v
public	schema_migrations	r
public	subscription_state	r
public	subscriptions	r
public	subscriptions_id_seq	S
EOF
}

_canonical_timescale_bindings() {
    cat <<'EOF'
public	observations	hypertable
public	observations_hourly	continuous_aggregate
EOF
}

_canonical_acl_columns() {
    cat <<'EOF'
public	alerts	acknowledged_at
public	alerts	last_sent_at
public	alerts	send_count
public	alerts	status
public	devices	fcm_token
public	devices	id
public	devices	is_admin
public	devices	last_seen
public	devices	platform
public	devices	secret_hash
public	eta_alerts	acknowledged_at
public	eta_alerts	last_sent_at
public	eta_alerts	send_count
public	eta_alerts	status
public	notification_cancels	abandoned_at
public	notification_cancels	accepted_at
public	notification_cancels	alert_id
public	notification_cancels	attempt_count
public	notification_cancels	kind
public	notification_cancels	last_attempt_at
EOF
}

validate_owned_object_allowlist() {
    local manifest=$1 expected actual extensions temporary
    [ -f "$manifest" ] || ownership_fail 'manifest not found'
    temporary=$(dirname "$manifest")
    expected=$(mktemp "$temporary/.expected.XXXXXX")
    actual=$(mktemp "$temporary/.actual.XXXXXX")
    extensions=$(mktemp "$temporary/.extensions.XXXXXX")
    chmod 600 "$expected" "$actual" "$extensions"

    _canonical_relations | LC_ALL=C sort >"$expected"
    awk -F '\t' '$1=="object" && $2=="relation" && $13=="application" {print $4 "\t" $5 "\t" $6}' \
        "$manifest" | LC_ALL=C sort >"$actual"
    if ! cmp -s "$expected" "$actual"; then
        rm -f "$expected" "$actual" "$extensions"
        ownership_fail 'application relation exact-set mismatch'
        return 1
    fi

    _canonical_timescale_bindings | LC_ALL=C sort >"$expected"
    awk -F '\t' '$1=="object" && $2=="timescale_binding" {print $4 "\t" $5 "\t" $6}' \
        "$manifest" | LC_ALL=C sort >"$actual"
    if ! cmp -s "$expected" "$actual"; then
        rm -f "$expected" "$actual" "$extensions"
        ownership_fail 'TimescaleDB application binding exact-set mismatch'
        return 1
    fi

    awk -F '\t' '$1=="object" && $2=="extension" {print $4 "\t" $5 "\t" $6}' \
        "$manifest" | LC_ALL=C sort >"$extensions"
    printf '%s\n' $'-\ttimescaledb\textension' >"$expected"
    if ! cmp -s "$expected" "$extensions"; then
        rm -f "$expected" "$actual" "$extensions"
        ownership_fail 'extension exact-set mismatch'
        return 1
    fi

    if ! awk -F '\t' -v target="${AVELREN_TARGET_DB:?AVELREN_TARGET_DB is required}" -v legacy="$AVELREN_LEGACY_ROLE" '
        $1=="object" && $2=="database" { databases++; if ($3 != target || $5 != target) bad=1 }
        $1=="object" && $2=="schema" && $13=="application" { schemas++; if ($4 != "public" || $5 != "public") bad=1 }
        $1=="object" && ($2=="tablespace" || $2=="shared" || $2=="default_acl" || $13=="shared") { bad=1 }
        $1=="object" && $13=="application" && ($2=="function" || $2=="type") { bad=1 }
        $1=="object" && $2!="column" && $7 != legacy { bad=1 }
        $1=="object" && $2=="column" && $7 != legacy { bad=1 }
        $1=="acl" && $11 !~ /^(SELECT|INSERT|UPDATE|DELETE|TRUNCATE|REFERENCES|TRIGGER|USAGE|CREATE|CONNECT|TEMPORARY|EXECUTE)$/ { bad=1 }
        END { exit !(databases==1 && schemas==1 && !bad) }
    ' "$manifest"; then
        rm -f "$expected" "$actual" "$extensions"
        ownership_fail 'owner, shared-object, or ACL contract mismatch'
        return 1
    fi

    rm -f "$expected" "$actual" "$extensions"
}

_write_plan_header() {
    cat <<'EOF'
-- Generated by deploy/postgres-ownership.lib.sh.
-- Contains identifiers and ACL statements only; no credentials.
\set ON_ERROR_STOP on
EOF
}

build_forward_plan() {
    local manifest=$1 output=$2 migration=$3 temporary schema name kind keyword
    validate_owned_object_allowlist "$manifest"
    [ "$(basename "$migration")" = 010_postgresql_least_privilege.sql ] || ownership_fail 'unexpected ACL migration path'
    [ -f "$migration" ] || ownership_fail 'ACL migration not found'
    temporary=$(_evidence_temp "$output")
    {
        _write_plan_header
        printf 'REASSIGN OWNED BY "%s" TO "%s";\n' "$AVELREN_LEGACY_ROLE" "$AVELREN_ADMIN_ROLE"
        while IFS=$'\t' read -r schema name kind; do
            case "$kind" in
                S) keyword=SEQUENCE ;;
                v)
                    if [ "$name" = observations_hourly ]; then keyword='MATERIALIZED VIEW'; else keyword=VIEW; fi
                    ;;
                m) keyword='MATERIALIZED VIEW' ;;
                r|p) keyword=TABLE ;;
                *) rm -f "$temporary"; ownership_fail 'unsupported relation kind in forward plan'; return 1 ;;
            esac
            printf 'ALTER %s "%s"."%s" OWNER TO "%s";\n' "$keyword" "$schema" "$name" "$AVELREN_MIGRATOR_ROLE"
        done < <(_canonical_relations)
        printf 'SET ROLE "%s";\n' "$AVELREN_MIGRATOR_ROLE"
        cat "$migration"
        printf '\n%s\n' 'RESET ROLE;'
    } >"$temporary"
    _publish_evidence_file "$temporary" "$output"
}

_role_sql() {
    local role=$1
    if [ "$role" = PUBLIC ]; then printf 'PUBLIC'; else printf '"%s"' "${role//\"/\"\"}"; fi
}

build_inverse_plan() {
    local manifest=$1 output=$2 temporary scope name kind owner subject grantor grantee privilege grantable source identity
    local object_keyword grantee_sql grantor_sql option role database_identity
    validate_owned_object_allowlist "$manifest"
    database_identity=$(awk -F '\t' '$1=="object" && $2=="database" {print $14}' "$manifest")
    [ -n "$database_identity" ] || ownership_fail 'validated database identity missing from manifest'
    temporary=$(_evidence_temp "$output")
    {
        _write_plan_header
        printf 'REASSIGN OWNED BY "%s" TO "%s";\n' "$AVELREN_MIGRATOR_ROLE" "$AVELREN_LEGACY_ROLE"
        printf 'REASSIGN OWNED BY "%s" TO "%s";\n' "$AVELREN_ADMIN_ROLE" "$AVELREN_LEGACY_ROLE"

        printf 'REVOKE ALL PRIVILEGES ON DATABASE %s FROM PUBLIC, "avelren_admin", "avelren_migrator", "avelren_backup", "avelren_collector", "avelren_notifier", "avelren_watchdog", "avelren_api";\n' "$database_identity"
        printf '%s\n' 'REVOKE ALL PRIVILEGES ON SCHEMA "public" FROM PUBLIC, "avelren_admin", "avelren_migrator", "avelren_backup", "avelren_collector", "avelren_notifier", "avelren_watchdog", "avelren_api";'
        while IFS=$'\t' read -r _ scope _ _ name kind owner subject _ _ _ _ source identity; do
            [ "$scope" = relation ] || continue
            [ "$source" = application ] || continue
            if [ "$kind" = S ]; then object_keyword=SEQUENCE; else object_keyword=TABLE; fi
            printf 'REVOKE ALL PRIVILEGES ON %s %s FROM PUBLIC, "avelren_admin", "avelren_migrator", "avelren_backup", "avelren_collector", "avelren_notifier", "avelren_watchdog", "avelren_api";\n' "$object_keyword" "$identity"
        done < <(awk -F '\t' '$1=="object" && $2=="relation"' "$manifest")
        while IFS=$'\t' read -r schema name subject; do
            printf 'REVOKE ALL PRIVILEGES ("%s") ON TABLE %s FROM PUBLIC, "avelren_admin", "avelren_migrator", "avelren_backup", "avelren_collector", "avelren_notifier", "avelren_watchdog", "avelren_api";\n' \
                "${subject//\"/\"\"}" "\"$schema\".\"$name\""
        done < <(_canonical_acl_columns)

        printf '%s\n' \
            'ALTER DEFAULT PRIVILEGES FOR ROLE "avelren_migrator" GRANT EXECUTE ON FUNCTIONS TO PUBLIC;' \
            'ALTER DEFAULT PRIVILEGES FOR ROLE "avelren_migrator" GRANT USAGE ON TYPES TO PUBLIC;'

        while IFS=$'\t' read -r _ scope _ _ name kind owner subject grantor grantee privilege grantable source identity; do
            [ "$source" = application ] || continue
            [ "$grantee" != "$owner" ] || continue
            grantee_sql=$(_role_sql "$grantee")
            grantor_sql=$(_role_sql "$grantor")
            option=
            [ "$grantable" = t ] && option=' WITH GRANT OPTION'
            printf 'SET ROLE %s;\n' "$grantor_sql"
            case "$scope:$subject:$kind" in
                database:object:*) printf 'GRANT %s ON DATABASE %s TO %s%s;\n' "$privilege" "$identity" "$grantee_sql" "$option" ;;
                schema:object:*) printf 'GRANT %s ON SCHEMA %s TO %s%s;\n' "$privilege" "$identity" "$grantee_sql" "$option" ;;
                relation:object:S) printf 'GRANT %s ON SEQUENCE %s TO %s%s;\n' "$privilege" "$identity" "$grantee_sql" "$option" ;;
                relation:object:*) printf 'GRANT %s ON TABLE %s TO %s%s;\n' "$privilege" "$identity" "$grantee_sql" "$option" ;;
                relation:*:*) printf 'GRANT %s ("%s") ON TABLE %s TO %s%s;\n' "$privilege" "${subject//\"/\"\"}" "$identity" "$grantee_sql" "$option" ;;
            esac
            printf '%s\n' 'RESET ROLE;'
        done < <(awk -F '\t' '$1=="acl"' "$manifest")
    } >"$temporary"
    _publish_evidence_file "$temporary" "$output"
}

_target_ownership_sql() {
    cat <<'SQL'
DO $avelren_verify$
BEGIN
    IF (SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=current_database()) <> 'avelren_admin' THEN
        RAISE EXCEPTION 'target database owner mismatch';
    END IF;
    IF (SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname='public') <> 'avelren_admin' THEN
        RAISE EXCEPTION 'public schema owner mismatch';
    END IF;
    IF (SELECT pg_get_userbyid(extowner) FROM pg_extension WHERE extname='timescaledb') <> 'avelren_admin' THEN
        RAISE EXCEPTION 'timescaledb extension owner mismatch';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relkind IN ('r','p','S','v','m')
          AND pg_get_userbyid(c.relowner) <> 'avelren_migrator'
    ) THEN
        RAISE EXCEPTION 'application owner mismatch';
    END IF;
END
$avelren_verify$;
SQL
}

validate_plan_round_trip() {
    local dsn=$1 manifest=$2 forward=$3 inverse=$4 directory driver raw normalized before after
    directory=$(dirname "$manifest")
    if [ -n "${AVELREN_CATALOG_FIXTURE_DIR:-}" ]; then
        { cat "$forward"; cat "$inverse"; } | _adoption_psql "$dsn" >/dev/null
        return
    fi
    driver=$(_evidence_temp "$directory/roundtrip.sql")
    raw=$(_evidence_temp "$directory/roundtrip.raw")
    normalized=$(_evidence_temp "$directory/roundtrip.tsv")
    {
        printf '%s\n' '\set ON_ERROR_STOP on' 'BEGIN;'
        cat "$forward"
        _target_ownership_sql
        cat "$inverse"
        _manifest_sql
        printf '%s\n' 'ROLLBACK;'
    } >"$driver"
    if ! _adoption_psql "$dsn" <"$driver" >"$raw"; then
        rm -f "$driver" "$raw" "$normalized"
        ownership_fail 'forward/inverse plan parse or round-trip failed'
        return 1
    fi
    if ! _normalize_manifest "$raw" "$normalized"; then
        rm -f "$driver" "$raw" "$normalized"
        ownership_fail 'round-trip manifest was malformed'
        return 1
    fi
    if ! cmp -s "$manifest" "$normalized"; then
        rm -f "$driver" "$raw" "$normalized"
        ownership_fail 'inverse plan fingerprint mismatch'
        return 1
    fi
    before=$(manifest_fingerprint "$manifest")
    capture_manifest "$dsn" "$directory/after-plan-validation.tsv"
    after=$(manifest_fingerprint "$directory/after-plan-validation.tsv")
    rm -f "$driver" "$raw" "$normalized"
    [ "$before" = "$after" ] || ownership_fail 'plan validation transaction changed catalog state'
}

verify_target_ownership() {
    local dsn=$1
    _target_ownership_sql | _adoption_psql "$dsn" >/dev/null
}

execute_before_commit_rollback() {
    local dsn=$1 manifest=$2 forward=$3 evidence_dir=$4 driver output status before after
    [ "${AVELREN_ADOPTION_FAILPOINT:-}" = before_commit ] || ownership_fail 'Task 6 requires before_commit failpoint'
    driver=$(_evidence_temp "$evidence_dir/before-commit.sql")
    output=$(_evidence_temp "$evidence_dir/before-commit.marker")
    {
        printf '%s\n' '\set ON_ERROR_STOP on' 'BEGIN;'
        awk '{ print; if ($0 == "REASSIGN OWNED BY \"avelren\" TO \"avelren_admin\";") exit }' "$forward"
        cat <<'SQL'
DO $avelren_first_mutation$
BEGIN
    IF (SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=current_database()) <> 'avelren_admin' THEN
        RAISE EXCEPTION 'first ownership mutation did not run';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relkind IN ('r','p','S','v','m')
          AND pg_get_userbyid(c.relowner) = 'avelren'
    ) THEN
        RAISE EXCEPTION 'first ownership mutation left legacy-owned application relations';
    END IF;
END
$avelren_first_mutation$;
SELECT 'FIRST_OWNERSHIP_MUTATION_EXECUTED';
SQL
        cat <<'SQL'
DO $avelren_failpoint$
BEGIN
    RAISE EXCEPTION 'AVELREN_ADOPTION_FAILPOINT=before_commit';
END
$avelren_failpoint$;
COMMIT;
SQL
    } >"$driver"
    set +e
    _adoption_psql "$dsn" <"$driver" >"$output"
    status=$?
    set -e
    rm -f "$driver"
    [ "$status" -ne 0 ] || ownership_fail 'before_commit failpoint did not abort transaction'
    grep -Fxq 'FIRST_OWNERSHIP_MUTATION_EXECUTED' "$output" || {
        rm -f "$output"
        ownership_fail 'first ownership mutation was not proven before failpoint'
        return 1
    }
    _publish_evidence_file "$output" "$evidence_dir/before-commit.marker"

    capture_manifest "$dsn" "$evidence_dir/after-failure.tsv"
    before=$(manifest_fingerprint "$manifest")
    after=$(manifest_fingerprint "$evidence_dir/after-failure.tsv")
    printf '%s\n' "$before" >"$evidence_dir/original.sha256"
    printf '%s\n' "$after" >"$evidence_dir/after-failure.sha256"
    chmod 600 "$evidence_dir/original.sha256" "$evidence_dir/after-failure.sha256"
    cmp -s "$manifest" "$evidence_dir/after-failure.tsv" || ownership_fail 'transaction rollback manifest mismatch'
    [ "$before" = "$after" ] || ownership_fail 'transaction rollback fingerprint mismatch'
}
