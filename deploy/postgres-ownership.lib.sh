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

adoption_signal_exit_status() {
    case "${1:-}" in
        HUP) printf '%s\n' 129 ;;
        INT) printf '%s\n' 130 ;;
        TERM) printf '%s\n' 143 ;;
        *)
            ownership_fail "unsupported adoption signal: ${1:-<empty>}"
            return 1
            ;;
    esac
}

prepare_evidence_dir() {
    local directory=$1 mode owner current_user
    [ ! -L "$directory" ] || {
        ownership_fail 'evidence directory must not be a symlink'
        return 1
    }
    if [ -e "$directory" ] && [ ! -d "$directory" ]; then
        ownership_fail 'evidence directory path is not a directory'
        return 1
    fi
    if ! mkdir -p -- "$directory"; then
        ownership_fail 'evidence directory creation failed'
        return 1
    fi
    [ -d "$directory" ] && [ ! -L "$directory" ] || {
        ownership_fail 'evidence directory became unsafe during creation'
        return 1
    }
    if ! chmod 700 -- "$directory"; then
        ownership_fail 'evidence directory mode update failed'
        return 1
    fi
    if ! mode=$(stat -c '%a' "$directory"); then
        ownership_fail 'evidence directory mode cannot be read'
        return 1
    fi
    [ "$mode" = 700 ] || {
        ownership_fail 'evidence directory mode must be 0700'
        return 1
    }
    if ! owner=$(stat -c '%u' "$directory"); then
        ownership_fail 'evidence directory owner cannot be read'
        return 1
    fi
    if ! current_user=$(id -u); then
        ownership_fail 'current evidence owner cannot be read'
        return 1
    fi
    [ "$owner" = "$current_user" ] || {
        ownership_fail 'evidence directory owner mismatch'
        return 1
    }
    return 0
}

_evidence_temp() {
    local target=$1 directory
    directory=$(dirname "$target") || return 1
    prepare_evidence_dir "$directory" || return 1
    mktemp "$directory/.ownership.XXXXXX" || return 1
}

_publish_evidence_file() {
    local temporary=$1 target=$2
    chmod 600 "$temporary" || return 1
    mv -fT "$temporary" "$target" || return 1
    chmod 600 "$target" || return 1
}

validate_protected_evidence_directory() {
    local directory=$1 label=$2
    [ -d "$directory" ] && [ ! -L "$directory" ] || {
        ownership_fail "$label is invalid"
        return 1
    }
    [ "$(stat -c '%a' "$directory")" = 700 ] || {
        ownership_fail "$label mode must be 0700"
        return 1
    }
    [ "$(stat -c '%u' "$directory")" = "$(id -u)" ] || {
        ownership_fail "$label owner mismatch"
        return 1
    }
}

validate_protected_evidence_file() {
    local file=$1 label=$2
    [ -f "$file" ] && [ ! -L "$file" ] || {
        ownership_fail "$label is invalid"
        return 1
    }
    [ "$(stat -c '%a' "$file")" = 600 ] || {
        ownership_fail "$label mode must be 0600"
        return 1
    }
    [ "$(stat -c '%u' "$file")" = "$(id -u)" ] || {
        ownership_fail "$label owner mismatch"
        return 1
    }
    [ "$(stat -c '%h' "$file")" = 1 ] || {
        ownership_fail "$label must not be hard-linked"
        return 1
    }
}

validate_protected_input_file() {
    local file=$1 label=$2 directory
    directory=$(dirname "$file") || return 1
    validate_protected_evidence_directory "$directory" "$label directory" || return 1
    validate_protected_evidence_file "$file" "$label file"
}

_adoption_psql() {
    local dsn=$1
    shift
    PGDATABASE="$dsn" "${AVELREN_PSQL_BIN:-psql}" -X -qAt -v ON_ERROR_STOP=1 "$@"
}

_manifest_sql() {
    local destination=${1:-stdout}
    cat <<'SQL'
WITH RECURSIVE
canonical_roles AS (
    SELECT oid AS role_oid, rolname AS role_name
    FROM pg_roles
    WHERE rolname IN ('avelren', 'avelren_admin', 'avelren_migrator')
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
    WHERE database.datname = current_database()
       -- Exclude the system databases (postgres/template0/template1) the cluster
       -- bootstrap `avelren` owns; they are never part of the adoption surface.
       OR (database.datdba IN (SELECT role_oid FROM canonical_roles)
           AND database.datname NOT IN ('postgres', 'template0', 'template1'))
),
timescale_extension AS (
    SELECT oid, extowner
    FROM pg_extension
    WHERE extname = 'timescaledb'
),
extension_members AS (
    SELECT dependency.classid, dependency.objid, dependency.objsubid
    FROM pg_depend AS dependency
    JOIN timescale_extension AS extension ON extension.oid = dependency.refobjid
    WHERE dependency.refclassid = 'pg_extension'::regclass
      AND dependency.deptype = 'e'
),
namespace_base AS (
    SELECT namespace.oid, namespace.nspname, namespace.nspowner, namespace.nspacl,
           pg_get_userbyid(namespace.nspowner) AS owner_name,
           format('%I', namespace.nspname) AS identity,
           CASE WHEN member.objid IS NOT NULL THEN 'timescale' ELSE 'application' END AS source,
           CASE WHEN member.objid IS NOT NULL THEN 'extension_member' ELSE 'root' END AS provenance
    FROM pg_namespace AS namespace
    LEFT JOIN extension_members AS member
      ON member.classid = 'pg_namespace'::regclass
     AND member.objid = namespace.oid
     AND member.objsubid = 0
    WHERE (namespace.nspname = 'public'
           OR namespace.nspowner IN (SELECT role_oid FROM canonical_roles))
      -- Exclude system schemas the bootstrap `avelren` owns; the `_timescaledb_*`
      -- schemas are owned by canonical roles too but are kept (classified
      -- timescale). No-op in the clusteradmin topology where clusteradmin owns
      -- these schemas.
      AND namespace.nspname NOT IN ('pg_catalog', 'information_schema')
      AND namespace.nspname NOT LIKE 'pg\_toast%'
      AND namespace.nspname NOT LIKE 'pg\_temp%'
       OR member.objid IS NOT NULL
),
extension_base AS (
    SELECT extension.oid, extension.extname, extension.extowner,
           pg_get_userbyid(extension.extowner) AS owner_name,
           format('%I', extension.extname) AS identity,
           CASE WHEN extension.extname = 'timescaledb' THEN 'timescale' ELSE 'extension' END AS source
    FROM pg_extension AS extension
    WHERE (extension.extname = 'timescaledb'
           OR extension.extowner IN (SELECT role_oid FROM canonical_roles))
      -- plpgsql is a pinned system-default extension; in the bootstrap topology
      -- the legacy `avelren` owns it, but it is part of the protected system
      -- surface, never the adoption surface. (In the clusteradmin topology it is
      -- owned by clusteradmin and was never captured, so this is a no-op there.)
      AND extension.extname <> 'plpgsql'
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
relation_edges AS (
    SELECT index_data.indexrelid AS child_oid, index_data.indrelid AS parent_oid, 'index'::text AS edge_kind
    FROM pg_index AS index_data
    UNION ALL
    SELECT relation.reltoastrelid, relation.oid, 'toast'
    FROM pg_class AS relation
    WHERE relation.reltoastrelid <> 0
    UNION ALL
    SELECT inheritance.inhrelid, inheritance.inhparent, 'inheritance'
    FROM pg_inherits AS inheritance
),
timescale_relation_roots AS (
    SELECT member.objid AS relation_oid, 'extension_member'::text AS provenance
    FROM extension_members AS member
    WHERE member.classid = 'pg_class'::regclass AND member.objsubid = 0
    UNION
    SELECT relation.oid, 'chunk_catalog'
    FROM _timescaledb_catalog.chunk AS chunk
    JOIN pg_namespace AS namespace ON namespace.nspname = chunk.schema_name
    JOIN pg_class AS relation
      ON relation.relnamespace = namespace.oid
     AND relation.relname = chunk.table_name
    UNION
    SELECT relation.oid, 'continuous_aggregate_materialization'
    FROM _timescaledb_catalog.continuous_agg AS aggregate
    JOIN _timescaledb_catalog.hypertable AS hypertable
      ON hypertable.id = aggregate.mat_hypertable_id
    JOIN pg_namespace AS namespace ON namespace.nspname = hypertable.schema_name
    JOIN pg_class AS relation
      ON relation.relnamespace = namespace.oid
     AND relation.relname = hypertable.table_name
    UNION
    SELECT relation.oid, 'compressed_hypertable'
    FROM _timescaledb_catalog.hypertable AS source_hypertable
    JOIN _timescaledb_catalog.hypertable AS compressed_hypertable
      ON compressed_hypertable.id = source_hypertable.compressed_hypertable_id
    JOIN pg_namespace AS namespace ON namespace.nspname = compressed_hypertable.schema_name
    JOIN pg_class AS relation
      ON relation.relnamespace = namespace.oid
     AND relation.relname = compressed_hypertable.table_name
    UNION
    SELECT relation.oid, 'continuous_aggregate_direct_view'
    FROM _timescaledb_catalog.continuous_agg AS aggregate
    JOIN pg_namespace AS namespace ON namespace.nspname = aggregate.direct_view_schema
    JOIN pg_class AS relation
      ON relation.relnamespace = namespace.oid
     AND relation.relname = aggregate.direct_view_name
    UNION
    SELECT relation.oid, 'continuous_aggregate_partial_view'
    FROM _timescaledb_catalog.continuous_agg AS aggregate
    JOIN pg_namespace AS namespace ON namespace.nspname = aggregate.partial_view_schema
    JOIN pg_class AS relation
      ON relation.relnamespace = namespace.oid
     AND relation.relname = aggregate.partial_view_name
),
relation_lineage(start_oid, current_oid, depth) AS (
    SELECT relation.oid, relation.oid, 0
    FROM pg_class AS relation
    UNION ALL
    SELECT lineage.start_oid, edge.parent_oid, lineage.depth + 1
    FROM relation_lineage AS lineage
    JOIN relation_edges AS edge ON edge.child_oid = lineage.current_oid
    WHERE lineage.depth < 32
),
relation_stats AS (
    SELECT lineage.start_oid,
           count(DISTINCT lineage.current_oid) FILTER (
               WHERE NOT EXISTS (
                   SELECT 1 FROM relation_edges AS parent_edge
                   WHERE parent_edge.child_oid = lineage.current_oid
               )
           ) AS root_count,
           min(lineage.current_oid) FILTER (
               WHERE NOT EXISTS (
                   SELECT 1 FROM relation_edges AS parent_edge
                   WHERE parent_edge.child_oid = lineage.current_oid
               )
           ) AS root_oid,
           bool_or(timescale_root.relation_oid IS NOT NULL) AS is_timescale,
           string_agg(DISTINCT timescale_root.provenance, ',' ORDER BY timescale_root.provenance)
               FILTER (WHERE timescale_root.relation_oid IS NOT NULL) AS timescale_provenance
    FROM relation_lineage AS lineage
    LEFT JOIN timescale_relation_roots AS timescale_root
      ON timescale_root.relation_oid = lineage.current_oid
    GROUP BY lineage.start_oid
),
relation_base AS (
    SELECT relation.oid, namespace.nspname, relation.relname, relation.relkind,
           relation.relowner, relation.relacl,
           pg_get_userbyid(relation.relowner) AS owner_name,
           format('%I.%I', namespace.nspname, relation.relname) AS identity,
           CASE WHEN stats.is_timescale THEN 'timescale' ELSE 'application' END AS source,
           CASE
             WHEN stats.root_count <> 1 THEN 'ambiguous'
             WHEN stats.is_timescale THEN
               format('timescale:%s:%s.%s', stats.timescale_provenance,
                      root_namespace.nspname, root_relation.relname)
             WHEN stats.root_oid = relation.oid THEN format('root:%s.%s', namespace.nspname, relation.relname)
             ELSE format('dependency:%s.%s', root_namespace.nspname, root_relation.relname)
           END AS provenance
    FROM pg_class AS relation
    JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    JOIN relation_stats AS stats ON stats.start_oid = relation.oid
    LEFT JOIN pg_class AS root_relation ON root_relation.oid = stats.root_oid
    LEFT JOIN pg_namespace AS root_namespace ON root_namespace.oid = root_relation.relnamespace
    WHERE (namespace.nspname = 'public'
           OR relation.relowner IN (SELECT role_oid FROM canonical_roles)
           OR stats.is_timescale)
      -- Session-local scratch relations are never part of the adoption surface.
      AND namespace.nspname NOT LIKE 'pg\_temp\_%'
      AND namespace.nspname NOT LIKE 'pg\_toast\_temp\_%'
      -- Production topology: the legacy `avelren` role is the cluster bootstrap
      -- superuser, so it owns the system catalogs too. Those are never part of
      -- the adoption surface and must stay owned by `avelren`; exclude them so
      -- the `relowner IN canonical_roles` clause above does not sweep them in.
      -- Key the exclusion on the dependency ROOT namespace, not the object's own
      -- schema: application TOAST tables live in pg_toast but are rooted in
      -- public and MUST stay in the surface, while system tables and their TOAST
      -- (rooted in pg_catalog / information_schema) are dropped. `_timescaledb_*`
      -- objects are rooted in public/timescale, so they are kept and classified
      -- as `timescale`.
      AND (root_namespace.nspname IS NULL
           OR root_namespace.nspname NOT IN ('pg_catalog', 'information_schema'))
),
routine_base AS (
    SELECT routine.oid, namespace.nspname, routine.proname, routine.prokind,
           routine.proowner, routine.proacl,
           pg_get_userbyid(routine.proowner) AS owner_name,
           format('%I.%I(%s)', namespace.nspname, routine.proname,
                  pg_get_function_identity_arguments(routine.oid)) AS identity,
           CASE WHEN member.objid IS NOT NULL THEN 'timescale' ELSE 'application' END AS source,
           CASE WHEN member.objid IS NOT NULL THEN 'extension_member' ELSE 'root' END AS provenance
    FROM pg_proc AS routine
    JOIN pg_namespace AS namespace ON namespace.oid = routine.pronamespace
    LEFT JOIN extension_members AS member
      ON member.classid = 'pg_proc'::regclass
     AND member.objid = routine.oid
     AND member.objsubid = 0
    WHERE (namespace.nspname = 'public'
           OR routine.proowner IN (SELECT role_oid FROM canonical_roles)
           OR member.objid IS NOT NULL)
      -- Production topology: exclude system catalogs the bootstrap `avelren`
      -- owns; they are never part of the adoption surface. (`_timescaledb_*`
      -- routines are extension members and remain captured/classified as
      -- `timescale`.)
      AND namespace.nspname NOT IN ('pg_catalog', 'information_schema')
      AND namespace.nspname NOT LIKE 'pg\_toast%'
),
type_edges AS (
    SELECT type.oid AS child_oid, type.typelem AS parent_oid
    FROM pg_type AS type
    WHERE type.typelem <> 0 AND type.typelem <> type.oid
    UNION
    SELECT range_data.rngmultitypid, range_data.rngtypid
    FROM pg_range AS range_data
    WHERE range_data.rngmultitypid <> 0
),
type_lineage(start_oid, current_oid, depth) AS (
    SELECT type.oid, type.oid, 0
    FROM pg_type AS type
    UNION ALL
    SELECT lineage.start_oid, edge.parent_oid, lineage.depth + 1
    FROM type_lineage AS lineage
    JOIN type_edges AS edge ON edge.child_oid = lineage.current_oid
    WHERE lineage.depth < 16
),
type_stats AS (
    SELECT lineage.start_oid,
           count(DISTINCT lineage.current_oid) FILTER (
               WHERE NOT EXISTS (
                   SELECT 1 FROM type_edges AS parent_edge
                   WHERE parent_edge.child_oid = lineage.current_oid
               )
           ) AS root_count,
           min(lineage.current_oid) FILTER (
               WHERE NOT EXISTS (
                   SELECT 1 FROM type_edges AS parent_edge
                   WHERE parent_edge.child_oid = lineage.current_oid
               )
           ) AS root_oid,
           bool_or(member.objid IS NOT NULL OR relation.source = 'timescale') AS is_timescale
    FROM type_lineage AS lineage
    JOIN pg_type AS current_type ON current_type.oid = lineage.current_oid
    LEFT JOIN extension_members AS member
      ON member.classid = 'pg_type'::regclass
     AND member.objid = current_type.oid
     AND member.objsubid = 0
    LEFT JOIN relation_base AS relation ON relation.oid = current_type.typrelid
    GROUP BY lineage.start_oid
),
type_base AS (
    SELECT type.oid, namespace.nspname, type.typname, type.typtype,
           type.typowner, type.typacl,
           pg_get_userbyid(type.typowner) AS owner_name,
           format('%I.%I', namespace.nspname, type.typname) AS identity,
           CASE WHEN stats.is_timescale THEN 'timescale' ELSE 'application' END AS source,
           CASE
             WHEN stats.root_count <> 1 THEN 'ambiguous'
             WHEN stats.is_timescale THEN format('timescale:type:%s.%s', root_namespace.nspname, root_type.typname)
             WHEN root_type.typrelid <> 0 AND stats.root_oid = type.oid THEN
               format('relation:%s.%s', root_relation_namespace.nspname, root_relation.relname)
             WHEN root_type.typrelid <> 0 THEN
               format('type:%s.%s', root_relation_namespace.nspname, root_relation.relname)
             ELSE format('root:%s.%s', root_namespace.nspname, root_type.typname)
           END AS provenance
    FROM pg_type AS type
    JOIN pg_namespace AS namespace ON namespace.oid = type.typnamespace
    JOIN type_stats AS stats ON stats.start_oid = type.oid
    LEFT JOIN pg_type AS root_type ON root_type.oid = stats.root_oid
    LEFT JOIN pg_namespace AS root_namespace ON root_namespace.oid = root_type.typnamespace
    LEFT JOIN pg_class AS root_relation ON root_relation.oid = root_type.typrelid
    LEFT JOIN pg_namespace AS root_relation_namespace ON root_relation_namespace.oid = root_relation.relnamespace
    WHERE (namespace.nspname = 'public'
           OR type.typowner IN (SELECT role_oid FROM canonical_roles)
           OR stats.is_timescale)
      -- Composite and array types implied by session-local scratch relations are
      -- never part of the adoption surface.
      AND namespace.nspname NOT LIKE 'pg\_temp\_%'
      AND namespace.nspname NOT LIKE 'pg\_toast\_temp\_%'
      -- Production topology: exclude system-catalog types the bootstrap
      -- `avelren` owns; they stay owned by `avelren` and are out of surface.
      AND namespace.nspname NOT IN ('pg_catalog', 'information_schema')
      AND namespace.nspname NOT LIKE 'pg\_toast%'
),
default_acl_base AS (
    SELECT defaults.oid, defaults.defaclrole, defaults.defaclnamespace,
           defaults.defaclobjtype, defaults.defaclacl,
           pg_get_userbyid(defaults.defaclrole) AS owner_name,
           namespace.nspname,
           format('%s:%s:%s', defaults.defaclrole, defaults.defaclnamespace,
                  defaults.defaclobjtype) AS identity
    FROM pg_default_acl AS defaults
    LEFT JOIN pg_namespace AS namespace ON namespace.oid = defaults.defaclnamespace
    WHERE defaults.defaclrole IN (SELECT role_oid FROM canonical_roles)
),
ownership_base AS (
    SELECT dependency.dbid, dependency.classid, dependency.objid, dependency.objsubid,
           owner_role.role_name AS owner_name
    FROM pg_shdepend AS dependency
    JOIN canonical_roles AS owner_role ON owner_role.role_oid = dependency.refobjid
    WHERE dependency.refclassid = 'pg_authid'::regclass
      AND dependency.deptype = 'o'
      AND (
          dependency.dbid = 0
          OR dependency.dbid = (SELECT oid FROM target_database)
      )
      -- Verification scratch tables live in the session temp schema and are not
      -- part of the adoption surface. Excluding them here keeps the manifest
      -- exact without depending on a fixed superuser name being available to
      -- own them away from the canonical roles.
      AND NOT (
          dependency.classid = 'pg_class'::regclass
          AND dependency.objid IN (
              SELECT relation.oid
              FROM pg_class AS relation
              JOIN pg_namespace AS relation_namespace
                ON relation_namespace.oid = relation.relnamespace
              WHERE relation_namespace.nspname LIKE 'pg\_temp\_%'
                 OR relation_namespace.nspname LIKE 'pg\_toast\_temp\_%'
          )
      )
),
ownership_classified AS (
    SELECT ownership.*,
           CASE
             WHEN ownership.classid = 'pg_database'::regclass
                  AND ownership.objid = (SELECT oid FROM target_database) THEN 'target_admin'
             WHEN ownership.classid = 'pg_database'::regclass
                  AND ownership.owner_name IN ('avelren_admin','avelren_migrator') THEN 'preserve'
             WHEN ownership_member.objid IS NOT NULL THEN 'timescale'
             WHEN ownership.classid = 'pg_namespace'::regclass
                  AND namespace.source = 'timescale' THEN 'timescale'
             WHEN ownership.classid = 'pg_namespace'::regclass
                  AND namespace.nspname = 'public' THEN 'target_admin'
             WHEN ownership.classid = 'pg_extension'::regclass
                  AND extension.extname = 'timescaledb' THEN 'timescale'
             WHEN ownership.classid = 'pg_class'::regclass
                  AND relation.source = 'timescale'
                  AND relation.provenance ~ '(chunk_catalog|continuous_aggregate|compressed_hypertable)'
                  THEN 'application_relation'
             WHEN ownership.classid = 'pg_class'::regclass
                  AND relation.source = 'timescale' THEN 'timescale'
             WHEN ownership.classid = 'pg_class'::regclass
                  AND relation.source = 'application' THEN 'application_relation'
             WHEN ownership.classid = 'pg_type'::regclass
                  AND type.source = 'timescale' THEN 'timescale'
             WHEN ownership.classid = 'pg_type'::regclass
                  AND type.source = 'application'
                  AND (type.provenance LIKE 'relation:%' OR type.provenance LIKE 'type:%')
                  THEN 'application_type'
             WHEN ownership.classid = 'pg_tablespace'::regclass
                  AND ownership.owner_name IN ('avelren_admin','avelren_migrator') THEN 'preserve'
             ELSE 'reject'
           END AS ownership_class,
           CASE
             WHEN relation.source IS NOT NULL THEN relation.source
             WHEN routine.source IS NOT NULL THEN routine.source
             WHEN type.source IS NOT NULL THEN type.source
             WHEN namespace.source IS NOT NULL THEN namespace.source
             WHEN extension.source IS NOT NULL THEN extension.source
             WHEN ownership_member.objid IS NOT NULL THEN 'timescale'
             ELSE 'shared'
           END AS source
    FROM ownership_base AS ownership
    LEFT JOIN namespace_base AS namespace
      ON ownership.classid = 'pg_namespace'::regclass AND namespace.oid = ownership.objid
    LEFT JOIN extension_base AS extension
      ON ownership.classid = 'pg_extension'::regclass AND extension.oid = ownership.objid
    LEFT JOIN relation_base AS relation
      ON ownership.classid = 'pg_class'::regclass AND relation.oid = ownership.objid
    LEFT JOIN routine_base AS routine
      ON ownership.classid = 'pg_proc'::regclass AND routine.oid = ownership.objid
    LEFT JOIN type_base AS type
      ON ownership.classid = 'pg_type'::regclass AND type.oid = ownership.objid
    LEFT JOIN extension_members AS ownership_member
      ON ownership_member.classid = ownership.classid
     AND ownership_member.objid = ownership.objid
     AND ownership_member.objsubid = ownership.objsubid
),
manifest_rows AS (
    SELECT ARRAY['object','database',datname,'-',datname,'database',owner_name,'-','-','-','-','-',source,identity]::text[] AS fields
    FROM database_inventory
    UNION ALL
    SELECT ARRAY['object','schema',current_database(),nspname,nspname,'schema',owner_name,provenance,'-','-','-','-',source,identity]::text[]
    FROM namespace_base
    UNION ALL
    SELECT ARRAY['object','extension',current_database(),'-',extname,'extension',owner_name,'-','-','-','-','-',source,identity]::text[]
    FROM extension_base
    UNION ALL
    SELECT ARRAY['object','timescale_binding',current_database(),nspname,relname,'hypertable',owner_name,'catalog','-','-','-','-','timescale',identity]::text[]
    FROM timescale_hypertable_base
    UNION ALL
    SELECT ARRAY['object','timescale_binding',current_database(),nspname,relname,'continuous_aggregate',owner_name,'catalog','-','-','-','-','timescale',identity]::text[]
    FROM timescale_continuous_aggregate_base
    UNION ALL
    SELECT ARRAY['object','relation',current_database(),nspname,relname,relkind::text,owner_name,provenance,'-','-','-','-',source,identity]::text[]
    FROM relation_base
    UNION ALL
    SELECT ARRAY['object','column',current_database(),relation.nspname,relation.relname,relation.relkind::text,
                 relation.owner_name,attribute.attname,'-','-','-','-',relation.source,relation.identity]::text[]
    FROM relation_base AS relation
    JOIN pg_attribute AS attribute ON attribute.attrelid = relation.oid
    WHERE attribute.attnum > 0 AND NOT attribute.attisdropped
    UNION ALL
    SELECT ARRAY['object','function',current_database(),nspname,proname,prokind::text,owner_name,provenance,'-','-','-','-',source,identity]::text[]
    FROM routine_base
    UNION ALL
    SELECT ARRAY['object','type',current_database(),nspname,typname,typtype::text,owner_name,provenance,'-','-','-','-',source,identity]::text[]
    FROM type_base
    UNION ALL
    SELECT ARRAY['object','tablespace','-', '-', tablespace.spcname,'tablespace',
                 pg_get_userbyid(tablespace.spcowner),'-','-','-','-','-','shared',format('%I', tablespace.spcname)]::text[]
    FROM pg_tablespace AS tablespace
    WHERE tablespace.spcowner IN (SELECT role_oid FROM canonical_roles)
    UNION ALL
    SELECT ARRAY['object','default_acl',current_database(),defaclnamespace::text,
                 oid::text,defaclobjtype::text,owner_name,'default_acl','-','-','-','-',
                 'application',identity]::text[]
    FROM default_acl_base
    UNION ALL
    SELECT ARRAY['object','ownership',dbid::text,classid::text,objid::text,objsubid::text,
                 owner_name,ownership_class,'-','-','-','-',source,
                 format('%s:%s:%s:%s', dbid, classid, objid, objsubid)]::text[]
    FROM ownership_classified
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
    UNION ALL
    SELECT ARRAY['acl','default_acl',current_database(),defaults.defaclnamespace::text,
                 defaults.oid::text,defaults.defaclobjtype::text,defaults.owner_name,'object',
                 pg_get_userbyid(acl.grantor),
                 CASE WHEN acl.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(acl.grantee) END,
                 acl.privilege_type,acl.is_grantable::text,'application',defaults.identity]::text[]
    FROM default_acl_base AS defaults
    CROSS JOIN LATERAL aclexplode(defaults.defaclacl) AS acl
)
SQL
    case "$destination" in
        stdout)
            cat <<'SQL'
SELECT array_to_string(fields, chr(9))
FROM manifest_rows
ORDER BY array_to_string(fields, chr(9)) COLLATE "C";
SQL
            ;;
        actual_table)
            cat <<'SQL'
INSERT INTO avelren_actual_manifest (row_text)
SELECT array_to_string(fields, chr(9))
FROM manifest_rows;
SQL
            ;;
        *) ownership_fail 'unknown manifest SQL destination'; return 1 ;;
    esac
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

publish_manifest_fingerprint() {
    local manifest=$1 output=$2 temporary
    if ! temporary=$(_evidence_temp "$output"); then
        ownership_fail 'manifest fingerprint temporary file creation failed'
        return 1
    fi
    if ! manifest_fingerprint "$manifest" >"$temporary"; then
        rm -f "$temporary"
        ownership_fail 'manifest fingerprint generation failed'
        return 1
    fi
    if ! _publish_evidence_file "$temporary" "$output"; then
        ownership_fail 'manifest fingerprint publication failed'
        return 1
    fi
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
    local manifest=$1 expected actual extensions allowed_roots temporary root unexpected_databases
    [ -f "$manifest" ] || ownership_fail 'manifest not found'
    temporary=$(dirname "$manifest")
    expected=$(mktemp "$temporary/.expected.XXXXXX")
    actual=$(mktemp "$temporary/.actual.XXXXXX")
    extensions=$(mktemp "$temporary/.extensions.XXXXXX")
    allowed_roots=$(mktemp "$temporary/.roots.XXXXXX")
    chmod 600 "$expected" "$actual" "$extensions" "$allowed_roots"

    _canonical_relations | LC_ALL=C sort >"$expected"
    awk -F '\t' '$1=="object" && $2=="relation" && $13=="application" && $8=="root:" $4 "." $5 {print $4 "\t" $5 "\t" $6}' \
        "$manifest" | LC_ALL=C sort >"$actual"
    if ! cmp -s "$expected" "$actual"; then
        rm -f "$expected" "$actual" "$extensions" "$allowed_roots"
        ownership_fail 'application relation exact-set mismatch'
        return 1
    fi
    awk -F '\t' '{print $1 "." $2}' "$expected" | LC_ALL=C sort -u >"$allowed_roots"
    while IFS= read -r root; do
        [ -z "$root" ] && continue
        grep -Fxq "$root" "$allowed_roots" || {
            rm -f "$expected" "$actual" "$extensions" "$allowed_roots"
            ownership_fail 'application relation dependency has an unknown root'
            return 1
        }
    done < <(awk -F '\t' '$1=="object" && $2=="relation" && $13=="application" && $8 ~ /^dependency:/ {sub(/^dependency:/,"",$8); print $8}' "$manifest" | LC_ALL=C sort -u)
    if awk -F '\t' '$1=="object" && $2=="relation" && $13=="application" && $8 !~ /^(root|dependency):/ {found=1} END {exit !found}' "$manifest"; then
        rm -f "$expected" "$actual" "$extensions" "$allowed_roots"
        ownership_fail 'application relation provenance is ambiguous'
        return 1
    fi

    while IFS= read -r root; do
        [ -z "$root" ] && continue
        grep -Fxq "$root" "$allowed_roots" || {
            rm -f "$expected" "$actual" "$extensions" "$allowed_roots"
            ownership_fail 'application type dependency has an unknown relation root'
            return 1
        }
    done < <(awk -F '\t' '$1=="object" && $2=="type" && $13=="application" && $8 ~ /^(relation|type):/ {sub(/^(relation|type):/,"",$8); print $8}' "$manifest" | LC_ALL=C sort -u)

    _canonical_timescale_bindings | LC_ALL=C sort >"$expected"
    awk -F '\t' '$1=="object" && $2=="timescale_binding" {print $4 "\t" $5 "\t" $6}' \
        "$manifest" | LC_ALL=C sort >"$actual"
    if ! cmp -s "$expected" "$actual"; then
        rm -f "$expected" "$actual" "$extensions" "$allowed_roots"
        ownership_fail 'TimescaleDB application binding exact-set mismatch'
        return 1
    fi

    awk -F '\t' '$1=="object" && $2=="extension" {print $4 "\t" $5 "\t" $6}' \
        "$manifest" | LC_ALL=C sort >"$extensions"
    printf '%s\n' $'-\ttimescaledb\textension' >"$expected"
    if ! cmp -s "$expected" "$extensions"; then
        rm -f "$expected" "$actual" "$extensions" "$allowed_roots"
        ownership_fail 'extension exact-set mismatch'
        return 1
    fi

    # An adopted cluster hosts exactly ONE database in the adoption surface: the
    # application target. `database_inventory` already drops the pinned system
    # databases (postgres/template0/template1), so any remaining non-application
    # row is a database some canonical role owns that nobody declared — a
    # disposable restore target left behind, a manual copy, a half-finished
    # migration. Adoption must refuse it BEFORE any mutation and say which one:
    # such a database is not inert (a leftover `restore_test` on production
    # 2026-08-14 kept a TimescaleDB background worker and scheduled compression
    # and continuous-aggregate policies running against the live instance), and
    # its ACL/ownership rows perturb the surface the plans are built from.
    unexpected_databases=$(awk -F '\t' '$1=="object" && $2=="database" && $13!="application" {print $5}' \
        "$manifest" | LC_ALL=C sort -u | tr '\n' ' ')
    if [ -n "${unexpected_databases% }" ]; then
        rm -f "$expected" "$actual" "$extensions" "$allowed_roots"
        ownership_fail "unexpected database owned by a canonical role: ${unexpected_databases% }"
        return 1
    fi

    if ! awk -F '\t' -v target="${AVELREN_TARGET_DB:?AVELREN_TARGET_DB is required}" -v legacy="$AVELREN_LEGACY_ROLE" '
        $1=="object" && $2=="database" && $13=="application" {
            databases++; if ($3 != target || $5 != target || $7 != legacy) bad=1
        }
        # Unreachable for database rows: the pre-check above refuses any
        # non-application database outright. Kept as a defence-in-depth floor in
        # case the pre-check is ever narrowed.
        $1=="object" && $2=="database" && $13=="shared" {
            if ($7 == legacy || ($7 != "avelren_admin" && $7 != "avelren_migrator")) bad=1
        }
        $1=="object" && $2=="schema" && $13=="application" {
            # public may be owned by the legacy role directly, or by the virtual
            # pg_database_owner role. The latter is safe ONLY because the
            # application-database row above independently asserts the database
            # owner is the legacy role, which is exactly who pg_database_owner
            # resolves to. Verified against production (avelren-Helsinki,
            # timescaledb 2.17.2-pg16): public.owner=pg_database_owner,
            # db.owner=avelren. The bootstrap-superuser topology never reassigns
            # public onto the legacy role, so this is the real production shape.
            schemas++; if ($4 != "public" || $5 != "public" || ($7 != legacy && $7 != "pg_database_owner") || $8 != "root") bad=1
        }
        $1=="object" && $2=="schema" && $13=="timescale" {
            if ($7 != legacy || $8 != "extension_member") bad=1
        }
        $1=="object" && $2=="extension" && $7 != legacy { bad=1 }
        $1=="object" && $2=="timescale_binding" && $7 != legacy { bad=1 }
        $1=="object" && ($2=="relation" || $2=="column" || $2=="function" || $2=="type") && $7 != legacy { bad=1 }
        $1=="object" && $2=="relation" && $13=="timescale" && $8 !~ /^timescale:/ { bad=1 }
        $1=="object" && $2=="function" && $13=="timescale" && $8 != "extension_member" { bad=1 }
        $1=="object" && $2=="type" && $13=="timescale" && $8 !~ /^timescale:/ { bad=1 }
        $1=="object" && $2=="function" && $13=="application" { bad=1 }
        $1=="object" && $2=="type" && $13=="application" && $8 !~ /^(relation|type):/ { bad=1 }
        $1=="object" && $2=="default_acl" { bad=1 }
        $1=="object" && $2=="tablespace" {
            # pg_default and pg_global are pinned built-in cluster tablespaces
            # owned by the bootstrap superuser; they cannot be reassigned, so in
            # the production bootstrap topology the legacy role legitimately owns
            # them (verified on avelren-Helsinki: both owned by avelren). Reject
            # only if some unexpected role holds them. Any user-created
            # tablespace still must have moved off legacy to admin/migrator.
            if ($5 == "pg_default" || $5 == "pg_global") {
                if ($7 != legacy && $7 != "avelren_admin" && $7 != "avelren_migrator") bad=1
            } else if ($7 == legacy || ($7 != "avelren_admin" && $7 != "avelren_migrator")) bad=1
        }
        $1=="object" && $2=="ownership" {
            ownership_rows++
            if ($8 == "reject") bad=1
            else if ($8 == "preserve") {
                if ($7 != "avelren_admin" && $7 != "avelren_migrator") bad=1
            } else if ($7 != legacy) bad=1
        }
        $1=="acl" && $11 !~ /^(SELECT|INSERT|UPDATE|DELETE|TRUNCATE|REFERENCES|TRIGGER|USAGE|CREATE|CONNECT|TEMPORARY|EXECUTE)$/ { bad=1 }
        # No ownership_rows>0 requirement: pg_shdepend does not record ownership
        # for the cluster bootstrap superuser, so in the production bootstrap
        # topology the legacy `avelren` legitimately produces zero `object
        # ownership` rows. databases==1 && schemas==1 already guard against an
        # empty/failed capture.
        END { exit !(databases==1 && schemas==1 && !bad) }
    ' "$manifest"; then
        rm -f "$expected" "$actual" "$extensions" "$allowed_roots"
        ownership_fail 'owner, shared-object, or ACL contract mismatch'
        return 1
    fi

    rm -f "$expected" "$actual" "$extensions" "$allowed_roots"
}

_write_plan_header() {
    cat <<'EOF'
-- Generated by deploy/postgres-ownership.lib.sh.
-- Contains identifiers and ACL statements only; no credentials.
\set ON_ERROR_STOP on
EOF
}

build_forward_plan() {
    local manifest=$1 output=$2 migration=$3 temporary schema name kind keyword database_identity subject
    # Check explicitly: `ownership_fail` only warns and returns 1, so an
    # unchecked call leaves the refusal enforced by `set -e` alone — and errexit
    # is suppressed whenever the caller sits in an `if`, `&&` or `||` context.
    # A validation failure must stop plan generation on its own merits.
    validate_owned_object_allowlist "$manifest" || return 1
    # Scope the identity to the APPLICATION database. The manifest legitimately
    # carries `shared` database rows (any other database a canonical role owns),
    # so an unscoped extraction returns several lines and silently produces a
    # multi-line, syntactically broken `... ON DATABASE <a>\n<b> FROM ...`.
    # Observed on production 2026-08-14: a leftover disposable `restore_test`
    # database owned by avelren_admin broke plan generation this way.
    # validate_owned_object_allowlist above now refuses such a topology outright;
    # this filter keeps the extraction correct by construction regardless.
    database_identity=$(awk -F '\t' '$1=="object" && $2=="database" && $13=="application" {print $14}' "$manifest")
    [ -n "$database_identity" ] || ownership_fail 'validated database identity missing from manifest'
    [ "$(basename "$migration")" = 010_postgresql_least_privilege.sql ] || ownership_fail 'unexpected ACL migration path'
    [ -f "$migration" ] || ownership_fail 'ACL migration not found'
    if ! temporary=$(_evidence_temp "$output"); then
        ownership_fail 'stage evidence temporary file creation failed'
        return 1
    fi
    {
        _write_plan_header
        # Bootstrap-superuser topology (Decision B): the legacy `avelren` is the
        # cluster bootstrap superuser and owns the database, `public` schema, the
        # timescaledb extension, the system catalogs, and all TimescaleDB
        # internals. Those MUST stay owned by `avelren`. The old blanket
        # `REASSIGN OWNED BY avelren TO avelren_admin` would sweep the whole
        # cluster (or, for a bootstrap role, silently skip pinned objects and
        # mis-model the surface), so it is removed. The only ownership change is
        # the explicit per-object transfer of the canonical application
        # relations to `avelren_migrator` below; everything else is preserved.
        printf 'REVOKE ALL PRIVILEGES ON DATABASE %s FROM PUBLIC, "avelren_migrator", "avelren_backup", "avelren_collector", "avelren_notifier", "avelren_watchdog", "avelren_api";\n' "$database_identity"
        printf 'GRANT CONNECT ON DATABASE %s TO "avelren_migrator", "avelren_backup", "avelren_collector", "avelren_notifier", "avelren_watchdog", "avelren_api";\n' "$database_identity"
        printf '%s\n' \
            'REVOKE ALL PRIVILEGES ON SCHEMA "public" FROM PUBLIC, "avelren_migrator", "avelren_backup", "avelren_collector", "avelren_notifier", "avelren_watchdog", "avelren_api";' \
            'GRANT USAGE, CREATE ON SCHEMA "public" TO "avelren_migrator";' \
            'GRANT USAGE ON SCHEMA "public" TO "avelren_backup", "avelren_collector", "avelren_notifier", "avelren_watchdog", "avelren_api";'
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
        while IFS=$'\t' read -r schema name kind; do
            if [ "$kind" = S ]; then keyword=SEQUENCE; else keyword=TABLE; fi
            printf 'REVOKE ALL PRIVILEGES ON %s "%s"."%s" FROM PUBLIC, "avelren_backup", "avelren_collector", "avelren_notifier", "avelren_watchdog", "avelren_api";\n' \
                "$keyword" "$schema" "$name"
        done < <(_canonical_relations)
        while IFS=$'\t' read -r schema name subject; do
            printf 'REVOKE ALL PRIVILEGES ("%s") ON TABLE "%s"."%s" FROM PUBLIC, "avelren_backup", "avelren_collector", "avelren_notifier", "avelren_watchdog", "avelren_api";\n' \
                "${subject//\"/\"\"}" "$schema" "$name"
        done < <(awk -F '\t' '$1=="acl" && $2=="relation" && $8!="object" && $13=="application" {print $4,$5,$8}' OFS='\t' "$manifest" | LC_ALL=C sort -u)
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
    local object_keyword grantee_sql grantor_sql option role database_identity schema keyword
    # Check explicitly: `ownership_fail` only warns and returns 1, so an
    # unchecked call leaves the refusal enforced by `set -e` alone — and errexit
    # is suppressed whenever the caller sits in an `if`, `&&` or `||` context.
    # A validation failure must stop plan generation on its own merits.
    validate_owned_object_allowlist "$manifest" || return 1
    # Scope the identity to the APPLICATION database. The manifest legitimately
    # carries `shared` database rows (any other database a canonical role owns),
    # so an unscoped extraction returns several lines and silently produces a
    # multi-line, syntactically broken `... ON DATABASE <a>\n<b> FROM ...`.
    # Observed on production 2026-08-14: a leftover disposable `restore_test`
    # database owned by avelren_admin broke plan generation this way.
    # validate_owned_object_allowlist above now refuses such a topology outright;
    # this filter keeps the extraction correct by construction regardless.
    database_identity=$(awk -F '\t' '$1=="object" && $2=="database" && $13=="application" {print $14}' "$manifest")
    [ -n "$database_identity" ] || ownership_fail 'validated database identity missing from manifest'
    temporary=$(_evidence_temp "$output")
    {
        _write_plan_header
        # Decision B inverse: the forward plan changed ownership of ONLY the
        # canonical application relations (avelren -> avelren_migrator). Reverse
        # exactly that, per object, back to the legacy `avelren`. No blanket
        # `REASSIGN OWNED`: database/schema/extension/system-catalog/TimescaleDB
        # ownership was never touched by the forward plan and must not be touched
        # here either.
        while IFS=$'\t' read -r schema name kind; do
            case "$kind" in
                S) keyword=SEQUENCE ;;
                v)
                    if [ "$name" = observations_hourly ]; then keyword='MATERIALIZED VIEW'; else keyword=VIEW; fi
                    ;;
                m) keyword='MATERIALIZED VIEW' ;;
                r|p) keyword=TABLE ;;
                *) rm -f "$temporary"; ownership_fail 'unsupported relation kind in inverse plan'; return 1 ;;
            esac
            printf 'ALTER %s "%s"."%s" OWNER TO "%s";\n' "$keyword" "$schema" "$name" "$AVELREN_LEGACY_ROLE"
        done < <(_canonical_relations)

        printf 'REVOKE ALL PRIVILEGES ON DATABASE %s FROM PUBLIC, "avelren_admin", "avelren_migrator", "avelren_backup", "avelren_collector", "avelren_notifier", "avelren_watchdog", "avelren_api";\n' "$database_identity"
        printf '%s\n' 'REVOKE ALL PRIVILEGES ON SCHEMA "public" FROM PUBLIC, "avelren_admin", "avelren_migrator", "avelren_backup", "avelren_collector", "avelren_notifier", "avelren_watchdog", "avelren_api";'
        while IFS=$'\t' read -r _ scope _ _ name kind owner subject _ _ _ _ source identity; do
            [ "$scope" = relation ] || continue
            [ "$source" = application ] || continue
            case "$subject" in root:*) ;; *) continue ;; esac
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
            case "$grantable" in
                t|true) option=' WITH GRANT OPTION' ;;
            esac
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

_emit_target_acl() {
    local scope=$1 schema=$2 name=$3 kind=$4 subject=$5 grantor=$6 grantee=$7
    shift 7
    local privilege
    for privilege in "$@"; do
        printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\tfalse\n' \
            "$scope" "$schema" "$name" "$kind" "$subject" "$grantor" "$grantee" "$privilege"
    done
}

_emit_target_relation_acl() {
    local name=$1 subject=$2 grantee=$3 kind=r
    shift 3
    case "$name" in
        *_id_seq) kind=S ;;
        observations_hourly) kind=v ;;
    esac
    _emit_target_acl relation public "$name" "$kind" "$subject" \
        "$AVELREN_MIGRATOR_ROLE" "$grantee" "$@"
}

_canonical_target_acl_rows() {
    local role name column
    # Decision B: the database and the public schema stay owned by the legacy
    # `avelren` (they are no longer reassigned to avelren_admin), so a superuser
    # GRANT on them records `avelren` — the owner — as the grantor.
    for role in avelren_migrator avelren_backup avelren_collector avelren_notifier avelren_watchdog avelren_api; do
        _emit_target_acl database - - database object avelren "$role" CONNECT
    done
    _emit_target_acl schema public public schema object avelren avelren_migrator USAGE CREATE
    for role in avelren_backup avelren_collector avelren_notifier avelren_watchdog avelren_api; do
        _emit_target_acl schema public public schema object avelren "$role" USAGE
    done

    for name in countries checkpoints observations observations_hourly collector_runs devices subscriptions subscription_state alerts eta_targets eta_alerts health_alerts notification_cancels schema_migrations \
        alerts_id_seq eta_alerts_id_seq health_alerts_id_seq notification_cancels_id_seq subscriptions_id_seq eta_targets_id_seq; do
        _emit_target_relation_acl "$name" object avelren_backup SELECT
    done

    for name in countries checkpoints observations collector_runs; do
        _emit_target_relation_acl "$name" object avelren_collector SELECT INSERT UPDATE
    done
    for name in subscriptions subscription_state alerts eta_targets eta_alerts; do
        _emit_target_relation_acl "$name" object avelren_collector SELECT
    done
    for name in subscription_state alerts eta_targets eta_alerts; do
        _emit_target_relation_acl "$name" object avelren_collector INSERT UPDATE
    done
    _emit_target_relation_acl notification_cancels object avelren_collector INSERT
    for column in kind alert_id; do
        _emit_target_relation_acl notification_cancels "$column" avelren_collector SELECT
    done
    for name in alerts_id_seq eta_alerts_id_seq notification_cancels_id_seq; do
        _emit_target_relation_acl "$name" object avelren_collector USAGE
    done

    for name in alerts eta_alerts subscriptions eta_targets checkpoints notification_cancels; do
        _emit_target_relation_acl "$name" object avelren_notifier SELECT
    done
    for column in id fcm_token; do
        _emit_target_relation_acl devices "$column" avelren_notifier SELECT
    done
    _emit_target_relation_acl devices fcm_token avelren_notifier UPDATE
    for name in alerts eta_alerts; do
        for column in last_sent_at send_count; do
            _emit_target_relation_acl "$name" "$column" avelren_notifier UPDATE
        done
    done
    for column in attempt_count last_attempt_at accepted_at abandoned_at; do
        _emit_target_relation_acl notification_cancels "$column" avelren_notifier UPDATE
    done
    _emit_target_relation_acl notification_cancels object avelren_notifier DELETE

    for name in observations collector_runs health_alerts; do
        _emit_target_relation_acl "$name" object avelren_watchdog SELECT
    done
    for column in id is_admin fcm_token; do
        _emit_target_relation_acl devices "$column" avelren_watchdog SELECT
    done
    # watchdog гасить мертвий адмін-FCM-токен (UPDATE devices SET fcm_token=NULL);
    # дзеркало GRANT UPDATE (fcm_token) ON devices TO avelren_watchdog у migration 010.
    _emit_target_relation_acl devices fcm_token avelren_watchdog UPDATE
    _emit_target_relation_acl health_alerts object avelren_watchdog INSERT UPDATE
    _emit_target_relation_acl health_alerts_id_seq object avelren_watchdog USAGE

    # Журнал міграцій читають і collector/notifier/watchdog — передумова
    # fail-closed старт-перевірки схеми (#88): сервіс має відмовитись стартувати
    # на схемі, старішій за ту, якої вимагає його код, а без цього SELECT така
    # перевірка впала б з 42501 одразу після 3C cutover. Дзеркало
    # `GRANT SELECT ON TABLE schema_migrations TO avelren_collector,
    # avelren_notifier, avelren_watchdog` у migration 010.
    for role in avelren_collector avelren_notifier avelren_watchdog; do
        _emit_target_relation_acl schema_migrations object "$role" SELECT
    done

    # schema_migrations: /admin/telemetry version-блок читає max(version) під роллю
    # avelren_api; дзеркало GRANT SELECT ON schema_migrations TO avelren_api у 010.
    for name in countries checkpoints observations observations_hourly collector_runs subscriptions alerts eta_targets eta_alerts health_alerts schema_migrations; do
        _emit_target_relation_acl "$name" object avelren_api SELECT
    done
    for column in id fcm_token platform secret_hash is_admin last_seen; do
        _emit_target_relation_acl devices "$column" avelren_api SELECT
    done
    for column in fcm_token platform secret_hash; do
        _emit_target_relation_acl devices "$column" avelren_api INSERT
    done
    for column in fcm_token last_seen; do
        _emit_target_relation_acl devices "$column" avelren_api UPDATE
    done
    for name in subscriptions eta_targets; do
        _emit_target_relation_acl "$name" object avelren_api INSERT UPDATE DELETE
    done
    for name in alerts eta_alerts; do
        for column in status acknowledged_at; do
            _emit_target_relation_acl "$name" "$column" avelren_api UPDATE
        done
    done
    _emit_target_relation_acl notification_cancels object avelren_api INSERT
    for column in kind alert_id; do
        _emit_target_relation_acl notification_cancels "$column" avelren_api SELECT
    done
    for name in subscriptions_id_seq eta_targets_id_seq notification_cancels_id_seq; do
        _emit_target_relation_acl "$name" object avelren_api USAGE
    done
}

_target_acl_sql() {
    cat <<'SQL'
CREATE TEMP TABLE avelren_expected_acl (
    scope text NOT NULL,
    schema_name text NOT NULL,
    object_name text NOT NULL,
    object_kind text NOT NULL,
    subject text NOT NULL,
    grantor_name text NOT NULL,
    grantee_name text NOT NULL,
    privilege_type text NOT NULL,
    is_grantable text NOT NULL
) ON COMMIT DROP;
COPY avelren_expected_acl FROM STDIN;
SQL
    _canonical_target_acl_rows | LC_ALL=C sort
    printf '%s\n' '\.'
    cat <<'SQL'
DO $avelren_acl_verify$
DECLARE
    mismatch_count bigint;
BEGIN
    WITH actual_acl AS (
        SELECT 'database'::text AS scope, '-'::text AS schema_name, '-'::text AS object_name,
               'database'::text AS object_kind, 'object'::text AS subject,
               pg_get_userbyid(acl.grantor) AS grantor_name,
               CASE WHEN acl.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(acl.grantee) END AS grantee_name,
               acl.privilege_type, acl.is_grantable::text
        FROM pg_database AS database
        CROSS JOIN LATERAL aclexplode(COALESCE(database.datacl, acldefault('d', database.datdba))) AS acl
        WHERE database.datname = current_database() AND acl.grantee <> database.datdba
        UNION ALL
        SELECT 'schema', namespace.nspname, namespace.nspname, 'schema', 'object',
               -- When public is owned by pg_database_owner (the production
               -- bootstrap topology), a GRANT by the database owner records the
               -- owning role, pg_database_owner, as the grantor. That role is
               -- avelren's proxy: the ownership check above already proved the
               -- database (hence pg_database_owner) resolves to avelren, so we
               -- normalise it to avelren for the exact-set comparison. Any other
               -- grantor still mismatches.
               CASE WHEN pg_get_userbyid(acl.grantor) = 'pg_database_owner'
                    THEN 'avelren' ELSE pg_get_userbyid(acl.grantor) END,
               CASE WHEN acl.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(acl.grantee) END,
               acl.privilege_type, acl.is_grantable::text
        FROM pg_namespace AS namespace
        CROSS JOIN LATERAL aclexplode(COALESCE(namespace.nspacl, acldefault('n', namespace.nspowner))) AS acl
        WHERE namespace.nspname = 'public' AND acl.grantee <> namespace.nspowner
        UNION ALL
        SELECT 'relation', namespace.nspname, relation.relname, relation.relkind::text, 'object',
               pg_get_userbyid(acl.grantor),
               CASE WHEN acl.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(acl.grantee) END,
               acl.privilege_type, acl.is_grantable::text
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        CROSS JOIN LATERAL aclexplode(COALESCE(
            relation.relacl,
            acldefault(CASE WHEN relation.relkind = 'S' THEN 's' ELSE 'r' END::"char", relation.relowner)
        )) AS acl
        WHERE namespace.nspname = 'public'
          AND relation.relkind IN ('r','p','S','v','m')
          AND acl.grantee <> relation.relowner
        UNION ALL
        SELECT 'relation', namespace.nspname, relation.relname, relation.relkind::text, attribute.attname,
               pg_get_userbyid(acl.grantor),
               CASE WHEN acl.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(acl.grantee) END,
               acl.privilege_type, acl.is_grantable::text
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        JOIN pg_attribute AS attribute ON attribute.attrelid = relation.oid
        CROSS JOIN LATERAL aclexplode(attribute.attacl) AS acl
        WHERE namespace.nspname = 'public'
          AND relation.relkind IN ('r','p','S','v','m')
          AND attribute.attnum > 0 AND NOT attribute.attisdropped
          AND attribute.attacl IS NOT NULL
          AND acl.grantee <> relation.relowner
    ), mismatch AS (
        (SELECT 'missing'::text AS direction, expected.* FROM avelren_expected_acl AS expected
         EXCEPT SELECT 'missing', actual.* FROM actual_acl AS actual)
        UNION ALL
        (SELECT 'unexpected'::text AS direction, actual.* FROM actual_acl AS actual
         EXCEPT SELECT 'unexpected', expected.* FROM avelren_expected_acl AS expected)
    )
    SELECT count(*) INTO mismatch_count FROM mismatch;
    IF mismatch_count <> 0 THEN
        RAISE EXCEPTION 'target ACL exact-set mismatch (% rows)', mismatch_count;
    END IF;

    WITH migrator AS (
        SELECT oid AS role_oid FROM pg_roles WHERE rolname = 'avelren_migrator'
    ), expected_default_acl AS (
        SELECT role_oid AS owner_oid, 0::oid AS namespace_oid, 'f'::"char" AS object_type,
               role_oid AS grantor_oid, role_oid AS grantee_oid,
               'EXECUTE'::text AS privilege_type, false AS is_grantable
        FROM migrator
        UNION ALL
        SELECT role_oid, 0::oid, 'T'::"char", role_oid, role_oid, 'USAGE'::text, false
        FROM migrator
    ), actual_default_acl AS (
        SELECT defaults.defaclrole, defaults.defaclnamespace, defaults.defaclobjtype,
               acl.grantor, acl.grantee, acl.privilege_type, acl.is_grantable
        FROM pg_default_acl AS defaults
        JOIN migrator ON migrator.role_oid = defaults.defaclrole
        CROSS JOIN LATERAL aclexplode(defaults.defaclacl) AS acl
    ), mismatch AS (
        (SELECT 'missing'::text AS direction, expected.*
         FROM expected_default_acl AS expected
         EXCEPT ALL
         SELECT 'missing', actual.* FROM actual_default_acl AS actual)
        UNION ALL
        (SELECT 'unexpected'::text AS direction, actual.*
         FROM actual_default_acl AS actual
         EXCEPT ALL
         SELECT 'unexpected', expected.* FROM expected_default_acl AS expected)
    )
    SELECT count(*) INTO mismatch_count FROM mismatch;
    IF mismatch_count <> 0 THEN
        RAISE EXCEPTION 'target default-privilege ACL exact-set mismatch (% rows)', mismatch_count;
    END IF;

    WITH migrator AS (
        SELECT oid AS role_oid FROM pg_roles WHERE rolname = 'avelren_migrator'
    ), expected_identity AS (
        SELECT role_oid AS owner_oid, 0::oid AS namespace_oid, 'f'::"char" AS object_type
        FROM migrator
        UNION ALL
        SELECT role_oid, 0::oid, 'T'::"char" FROM migrator
    ), actual_identity AS (
        SELECT defaults.defaclrole, defaults.defaclnamespace, defaults.defaclobjtype
        FROM pg_default_acl AS defaults
        JOIN migrator ON migrator.role_oid = defaults.defaclrole
    ), mismatch AS (
        (SELECT 'missing'::text AS direction, expected.*
         FROM expected_identity AS expected
         EXCEPT ALL
         SELECT 'missing', actual.* FROM actual_identity AS actual)
        UNION ALL
        (SELECT 'unexpected'::text AS direction, actual.*
         FROM actual_identity AS actual
         EXCEPT ALL
         SELECT 'unexpected', expected.* FROM expected_identity AS expected)
    )
    SELECT count(*) INTO mismatch_count FROM mismatch;
    IF mismatch_count <> 0 THEN
        RAISE EXCEPTION 'target default-privilege identity exact-set mismatch (% rows)', mismatch_count;
    END IF;
END
$avelren_acl_verify$;
DROP TABLE avelren_expected_acl;
SQL
}

_target_ownership_sql() {
    local manifest=${1:?ownership manifest is required}
    # Ownership verification runs BEFORE the ACL verification: an ownership drift
    # (e.g. a canonical relation left off avelren_migrator) also perturbs ACL
    # attribution, so the ownership check must fire first to report the precise
    # cause; ACL-only tampers pass ownership and are caught by _target_acl_sql.
    cat <<'SQL'
CREATE TEMP TABLE avelren_canonical_app (schema_name text, object_name text, kind text) ON COMMIT DROP;
COPY avelren_canonical_app (schema_name, object_name, kind) FROM STDIN;
SQL
    _canonical_relations
    printf '%s\n' '\.'
    cat <<'SQL'
-- Base application relations that end up owned by avelren_migrator: the
-- canonical relations PLUS the TimescaleDB internals that `ALTER ... OWNER`
-- cascades along with an adopted hypertable / continuous aggregate (its chunks,
-- compressed + materialization hypertables, and cagg partial/direct views).
-- pg_depend does NOT model this cascade, so it is resolved from the TimescaleDB
-- catalog. This is the reality proven by the bootstrap-topology integration test.
CREATE TEMP TABLE avelren_base_rel ON COMMIT DROP AS
WITH RECURSIVE adopted_ht(id) AS (
    SELECT h.id FROM _timescaledb_catalog.hypertable h
    JOIN avelren_canonical_app a ON a.schema_name = h.schema_name AND a.object_name = h.table_name
    UNION
    SELECT ca.mat_hypertable_id FROM _timescaledb_catalog.continuous_agg ca
    JOIN avelren_canonical_app a ON a.schema_name = ca.user_view_schema AND a.object_name = ca.user_view_name
    UNION
    SELECT h.compressed_hypertable_id FROM _timescaledb_catalog.hypertable h
    JOIN adopted_ht ah ON ah.id = h.id WHERE h.compressed_hypertable_id IS NOT NULL
), ts_relnames(s, t) AS (
    SELECT h.schema_name, h.table_name
    FROM _timescaledb_catalog.hypertable h JOIN adopted_ht ah ON ah.id = h.id
    UNION
    SELECT c.schema_name, c.table_name
    FROM _timescaledb_catalog.chunk c JOIN adopted_ht ah ON ah.id = c.hypertable_id
    UNION
    SELECT ca.partial_view_schema, ca.partial_view_name
    FROM _timescaledb_catalog.continuous_agg ca
    JOIN avelren_canonical_app a ON a.schema_name = ca.user_view_schema AND a.object_name = ca.user_view_name
    UNION
    SELECT ca.direct_view_schema, ca.direct_view_name
    FROM _timescaledb_catalog.continuous_agg ca
    JOIN avelren_canonical_app a ON a.schema_name = ca.user_view_schema AND a.object_name = ca.user_view_name
)
SELECT c.oid
FROM avelren_canonical_app a
JOIN pg_namespace n ON n.nspname = a.schema_name
JOIN pg_class c ON c.relnamespace = n.oid AND c.relname = a.object_name
UNION
SELECT r.oid
FROM ts_relnames x
JOIN pg_class r ON r.oid = to_regclass(format('%I.%I', x.s, x.t));

-- Full ownership closure: base relations + the objects PostgreSQL co-owns with
-- them on ALTER ... OWNER — indexes, TOAST tables and their indexes, composite
-- rowtypes and array types. Enumerated explicitly (pg_index / reltoastrelid /
-- reltype / typarray) rather than via pg_depend deptype, so constraint-backed
-- (primary-key / unique) indexes are captured too.
CREATE TEMP TABLE avelren_app_closure ON COMMIT DROP AS
SELECT 'pg_class'::regclass::oid AS classid, oid AS objid FROM avelren_base_rel
UNION
SELECT 'pg_class'::regclass::oid, i.indexrelid FROM pg_index i
 WHERE i.indrelid IN (SELECT oid FROM avelren_base_rel)
UNION
SELECT 'pg_class'::regclass::oid, c.reltoastrelid FROM pg_class c
 WHERE c.oid IN (SELECT oid FROM avelren_base_rel) AND c.reltoastrelid <> 0
UNION
SELECT 'pg_class'::regclass::oid, ti.indexrelid FROM pg_index ti
 WHERE ti.indrelid IN (SELECT reltoastrelid FROM pg_class WHERE oid IN (SELECT oid FROM avelren_base_rel) AND reltoastrelid <> 0)
UNION
SELECT 'pg_type'::regclass::oid, c.reltype FROM pg_class c
 WHERE c.oid IN (SELECT oid FROM avelren_base_rel) AND c.reltype <> 0
UNION
SELECT 'pg_type'::regclass::oid, t.typarray FROM pg_type t
 WHERE t.oid IN (SELECT reltype FROM pg_class WHERE oid IN (SELECT oid FROM avelren_base_rel) AND reltype <> 0)
   AND t.typarray <> 0;

-- Protected TimescaleDB EXTENSION surface that must NOT move to migrator/admin:
-- the extension's own catalog / config / function schemas and its extension
-- members. `_timescaledb_internal` is DELIBERATELY excluded — it holds the
-- adopted-hypertable data that TimescaleDB moves to the new owner along with the
-- hypertable, and which is therefore part of the application closure above.
CREATE TEMP TABLE avelren_protected_surface ON COMMIT DROP AS
SELECT 'pg_class'::regclass::oid AS classid, c.oid AS objid
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname IN ('_timescaledb_catalog','_timescaledb_config','_timescaledb_functions',
                    '_timescaledb_cache','_timescaledb_debug','timescaledb_information','timescaledb_experimental')
UNION
SELECT 'pg_type'::regclass::oid, t.oid
FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
WHERE n.nspname IN ('_timescaledb_catalog','_timescaledb_config','_timescaledb_functions',
                    '_timescaledb_cache','_timescaledb_debug','timescaledb_information','timescaledb_experimental')
UNION
SELECT dep.classid, dep.objid
FROM pg_depend dep
JOIN pg_extension e ON e.oid = dep.refobjid AND e.extname = 'timescaledb'
WHERE dep.refclassid = 'pg_extension'::regclass AND dep.deptype = 'e'
  AND dep.classid IN ('pg_class'::regclass, 'pg_type'::regclass);

DO $avelren_verify$
DECLARE
    detail text;
    canonical_total bigint;
    canonical_present bigint;
BEGIN
    -- Decision B (bootstrap-superuser topology): the legacy `avelren` is the
    -- cluster owner. The ONLY ownership change adoption performs is moving the
    -- canonical application relations to `avelren_migrator`. Positive allowlist:
    --   * protected top-level objects (database, public schema, timescaledb
    --     extension) stay owned by `avelren`;
    --   * the application closure is disjoint from the protected surface;
    --   * `avelren_migrator` owns EXACTLY the application closure — no more;
    --   * `avelren_admin` owns nothing in either surface.

    -- (1-3) Protected top-level ownership is preserved on the legacy `avelren`.
    IF (SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=current_database()) <> 'avelren' THEN
        RAISE EXCEPTION 'target ownership: database is not owned by avelren';
    END IF;
    -- public may be owned by avelren directly or by the virtual
    -- pg_database_owner role. The latter is safe because the check above already
    -- proved the database is owned by avelren, which is exactly who
    -- pg_database_owner resolves to (verified on avelren-Helsinki prod:
    -- public.owner=pg_database_owner, db.owner=avelren).
    IF (SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname='public')
           NOT IN ('avelren','pg_database_owner') THEN
        RAISE EXCEPTION 'target ownership: public schema is not owned by avelren or pg_database_owner';
    END IF;
    IF (SELECT pg_get_userbyid(extowner) FROM pg_extension WHERE extname='timescaledb') <> 'avelren' THEN
        RAISE EXCEPTION 'target ownership: timescaledb extension is not owned by avelren';
    END IF;
    -- The canonical relations must all exist exactly once.
    SELECT count(*) INTO canonical_total FROM avelren_canonical_app;
    SELECT count(*) INTO canonical_present
      FROM avelren_canonical_app a
      JOIN pg_namespace n ON n.nspname = a.schema_name
      JOIN pg_class c ON c.relnamespace = n.oid AND c.relname = a.object_name;
    IF canonical_present <> canonical_total THEN
        RAISE EXCEPTION 'target ownership: expected % canonical relations, found %', canonical_total, canonical_present;
    END IF;

    -- (invariant) the application closure and the protected TimescaleDB surface
    -- are disjoint. A chunk/internal object pulled into the closure (e.g. via an
    -- ALTER on the continuous-aggregate view) is caught here rather than silently
    -- transferred.
    SELECT string_agg(pg_describe_object(p.classid, p.objid, 0), '; ')
      INTO detail
      FROM avelren_app_closure ac
      JOIN avelren_protected_surface p ON p.classid = ac.classid AND p.objid = ac.objid;
    IF detail IS NOT NULL THEN
        RAISE EXCEPTION 'target ownership: application closure intersects the protected TimescaleDB surface: %', detail;
    END IF;

    -- (4 & 7) Every object in the application closure is owned by avelren_migrator
    -- (so none of the canonical relations remain owned by avelren).
    SELECT string_agg(format('%s=%s', pg_describe_object(ac.classid, ac.objid, 0),
                             pg_get_userbyid(o.owner_oid)), '; ')
      INTO detail
      FROM avelren_app_closure ac
      CROSS JOIN LATERAL (
          SELECT CASE ac.classid
                   WHEN 'pg_class'::regclass THEN (SELECT relowner FROM pg_class WHERE oid = ac.objid)
                   WHEN 'pg_type'::regclass THEN (SELECT typowner FROM pg_type WHERE oid = ac.objid)
                 END AS owner_oid
      ) o
     WHERE pg_get_userbyid(o.owner_oid) IS DISTINCT FROM 'avelren_migrator';
    IF detail IS NOT NULL THEN
        RAISE EXCEPTION 'target ownership: application object not owned by avelren_migrator: %', detail;
    END IF;

    -- (5) avelren_migrator owns EXACTLY the closure: nothing outside it. A
    -- TimescaleDB chunk or internal object mis-transferred to migrator is caught.
    SELECT string_agg(pg_describe_object(x.classid, x.objid, 0), '; ')
      INTO detail
      FROM (
          SELECT 'pg_class'::regclass::oid AS classid, c.oid AS objid
          FROM pg_class c WHERE c.relowner = (SELECT oid FROM pg_roles WHERE rolname='avelren_migrator')
          UNION ALL
          SELECT 'pg_type'::regclass::oid, t.oid
          FROM pg_type t WHERE t.typowner = (SELECT oid FROM pg_roles WHERE rolname='avelren_migrator')
      ) x
      LEFT JOIN avelren_app_closure ac ON ac.classid = x.classid AND ac.objid = x.objid
     WHERE ac.objid IS NULL;
    IF detail IS NOT NULL THEN
        RAISE EXCEPTION 'target ownership: avelren_migrator owns objects outside the canonical closure (over-transfer): %', detail;
    END IF;

    -- (5b) avelren_migrator owns no routines (adoption never transfers functions).
    IF EXISTS (SELECT 1 FROM pg_proc WHERE proowner = (SELECT oid FROM pg_roles WHERE rolname='avelren_migrator')) THEN
        RAISE EXCEPTION 'target ownership: avelren_migrator unexpectedly owns routines';
    END IF;

    -- (6) avelren_admin owns nothing in the application closure or protected surface.
    SELECT string_agg(pg_describe_object(s.classid, s.objid, 0), '; ')
      INTO detail
      FROM (SELECT classid, objid FROM avelren_app_closure
            UNION
            SELECT classid, objid FROM avelren_protected_surface) s
      CROSS JOIN LATERAL (
          SELECT CASE s.classid
                   WHEN 'pg_class'::regclass THEN (SELECT relowner FROM pg_class WHERE oid = s.objid)
                   WHEN 'pg_type'::regclass THEN (SELECT typowner FROM pg_type WHERE oid = s.objid)
                 END AS owner_oid
      ) o
     WHERE pg_get_userbyid(o.owner_oid) = 'avelren_admin';
    IF detail IS NOT NULL THEN
        RAISE EXCEPTION 'target ownership: avelren_admin owns application/timescale objects: %', detail;
    END IF;
END
$avelren_verify$;
DROP TABLE avelren_app_closure;
DROP TABLE avelren_protected_surface;
DROP TABLE avelren_base_rel;
DROP TABLE avelren_canonical_app;
SQL
    _target_acl_sql
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
        _target_ownership_sql "$manifest"
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
    local dsn=$1 manifest=$2
    {
        printf '%s\n' '\set ON_ERROR_STOP on' 'BEGIN;'
        _target_ownership_sql "$manifest"
        printf '%s\n' 'ROLLBACK;'
    } | _adoption_psql "$dsn" >/dev/null
}

execute_before_commit_rollback() {
    local dsn=$1 manifest=$2 forward=$3 evidence_dir=$4 driver output status before after
    [ "${AVELREN_ADOPTION_FAILPOINT:-}" = before_commit ] || ownership_fail 'Task 6 requires before_commit failpoint'
    driver=$(_evidence_temp "$evidence_dir/before-commit.sql")
    output=$(_evidence_temp "$evidence_dir/before-commit.marker")
    {
        printf '%s\n' '\set ON_ERROR_STOP on' 'BEGIN;'
        # Decision B: the forward plan no longer begins with a blanket REASSIGN;
        # the first ownership mutation is the first per-object handoff of a
        # canonical relation to avelren_migrator. Apply the plan up to and
        # including that first `ALTER ... OWNER TO "avelren_migrator";`, then
        # prove it ran and hit the failpoint so the whole transaction rolls back.
        awk '{ print } /OWNER TO "avelren_migrator";/ { exit }' "$forward"
        cat <<'SQL'
DO $avelren_first_mutation$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relkind IN ('r','p','S','v','m')
          AND pg_get_userbyid(c.relowner) = 'avelren_migrator'
    ) THEN
        RAISE EXCEPTION 'first ownership mutation did not run';
    END IF;
    -- Decision B invariant: the database stays owned by the legacy avelren.
    IF (SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=current_database()) <> 'avelren' THEN
        RAISE EXCEPTION 'database owner unexpectedly changed during first mutation';
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
    publish_manifest_fingerprint "$manifest" "$evidence_dir/original.sha256"
    publish_manifest_fingerprint "$evidence_dir/after-failure.tsv" \
        "$evidence_dir/after-failure.sha256"
    cmp -s "$manifest" "$evidence_dir/after-failure.tsv" || ownership_fail 'transaction rollback manifest mismatch'
    [ "$before" = "$after" ] || ownership_fail 'transaction rollback fingerprint mismatch'
}

publish_adoption_stage() {
    local output=$1 exact_commit=$2 stage=$3 original_fingerprint=$4 target_fingerprint=$5
    local inverse_verified=$6 privilege_result=$7 isolation_result=$8 smoke_result=$9 freshness_result=${10}
    local accepted_cutover=${11:-NOT_RUN} temporary
    [[ "$exact_commit" =~ ^[0-9a-f]{40}$ ]] || {
        ownership_fail 'stage evidence commit is invalid'
        return 1
    }
    [[ "$original_fingerprint" =~ ^[0-9a-f]{64}$ ]] || {
        ownership_fail 'stage evidence original fingerprint is invalid'
        return 1
    }
    [[ "$target_fingerprint" = - || "$target_fingerprint" =~ ^[0-9a-f]{64}$ ]] || {
        ownership_fail 'stage evidence target fingerprint is invalid'
        return 1
    }
    case "$stage" in committed|cutover_complete|post_commit_rollback|rollback_failed) ;; *) ownership_fail 'stage evidence stage is invalid'; return 1 ;; esac
    for result in "$inverse_verified" "$privilege_result" "$isolation_result" "$smoke_result" "$freshness_result" "$accepted_cutover"; do
        case "$result" in PASS|FAIL|NOT_RUN) ;; *) ownership_fail 'stage evidence result is invalid'; return 1 ;; esac
    done
    if ! temporary=$(_evidence_temp "$output"); then
        ownership_fail 'stage evidence temporary file creation failed'
        return 1
    fi
    {
        printf 'exact_commit=%s\n' "$exact_commit"
        printf 'stage=%s\n' "$stage"
        printf 'original_fingerprint=%s\n' "$original_fingerprint"
        printf 'target_fingerprint=%s\n' "$target_fingerprint"
        printf 'inverse_verified=%s\n' "$inverse_verified"
        printf 'privilege_contract_result=%s\n' "$privilege_result"
        printf 'environment_isolation_result=%s\n' "$isolation_result"
        printf 'smoke_result=%s\n' "$smoke_result"
        printf 'freshness_result=%s\n' "$freshness_result"
        printf 'accepted_cutover=%s\n' "$accepted_cutover"
    } >"$temporary" || {
        rm -f "$temporary"
        ownership_fail 'stage evidence generation failed'
        return 1
    }
    if ! _publish_evidence_file "$temporary" "$output"; then
        rm -f "$temporary"
        ownership_fail 'stage evidence publication failed'
        return 1
    fi
}

publish_legacy_retirement_attempt() {
    local output=$1 exact_commit=$2 temporary
    if [[ ! "$exact_commit" =~ ^[0-9a-f]{40}$ ]] && [ "$exact_commit" != NOT_VERIFIED ]; then
        ownership_fail 'retirement attempt commit is invalid'
        return 1
    fi
    temporary=$(_evidence_temp "$output") || {
        ownership_fail 'retirement attempt evidence temporary file creation failed'
        return 1
    }
    {
        printf 'exact_commit=%s\n' "$exact_commit"
        printf '%s\n' \
            'stage=legacy_retirement_in_progress' \
            'legacy_credential_retired=NOT_VERIFIED'
    } >"$temporary" || {
        rm -f "$temporary"
        ownership_fail 'retirement attempt evidence generation failed'
        return 1
    }
    if ! _publish_evidence_file "$temporary" "$output"; then
        rm -f "$temporary"
        ownership_fail 'retirement attempt evidence publication failed'
        return 1
    fi
}

validate_legacy_retirement_attempt() {
    local file=$1 exact_commit=$2
    local -a lines
    validate_protected_evidence_file "$file" 'legacy retirement attempt evidence' || return 1
    mapfile -t lines <"$file" || {
        ownership_fail 'legacy retirement attempt evidence cannot be read'
        return 1
    }
    [ "${#lines[@]}" -eq 3 ] && \
        [ "${lines[0]}" = "exact_commit=$exact_commit" ] && \
        [ "${lines[1]}" = 'stage=legacy_retirement_in_progress' ] && \
        [ "${lines[2]}" = 'legacy_credential_retired=NOT_VERIFIED' ] || {
        ownership_fail 'legacy retirement attempt evidence is inconsistent'
        return 1
    }
}

invalidate_legacy_retirement_success() {
    local evidence_dir=$1 exact_commit=$2 output
    output="$evidence_dir/legacy-retirement"
    validate_protected_evidence_directory "$evidence_dir" 'adoption evidence directory' || return 1
    if [ -e "$output" ] || [ -L "$output" ]; then
        validate_protected_evidence_file "$output" 'legacy retirement evidence file' || {
            ownership_fail 'legacy retirement evidence file is invalid'
            return 1
        }
    fi
    if ! rm -f -- "$output"; then
        ownership_fail 'legacy retirement authoritative evidence invalidation failed'
        return 1
    fi
    if [ -e "$output" ] || [ -L "$output" ]; then
        ownership_fail 'legacy retirement authoritative evidence invalidation did not remove the path'
        return 1
    fi
    publish_legacy_retirement_attempt "$output" "$exact_commit" || return 1
    validate_legacy_retirement_attempt "$output" "$exact_commit"
}

publish_legacy_retirement() {
    local output=$1 exact_commit=$2 target_fingerprint=$3 post_fingerprint=$4
    local privilege_result=$5 isolation_result=$6 accepted_soak=$7 temporary
    [[ "$exact_commit" =~ ^[0-9a-f]{40}$ ]] || {
        ownership_fail 'retirement evidence commit is invalid'
        return 1
    }
    [[ "$target_fingerprint" =~ ^[0-9a-f]{64}$ ]] || {
        ownership_fail 'retirement target fingerprint is invalid'
        return 1
    }
    [ "$post_fingerprint" = "$target_fingerprint" ] || {
        ownership_fail 'retirement fingerprint changed'
        return 1
    }
    for result in "$privilege_result" "$isolation_result" "$accepted_soak"; do
        [ "$result" = PASS ] || { ownership_fail 'retirement evidence result is not PASS'; return 1; }
    done
    validate_legacy_retirement_attempt "$output" "$exact_commit" || return 1
    if [ "${AVELREN_RETIREMENT_FAILPOINT:-}" = publication ]; then
        export AVELREN_RETIREMENT_PUBLISH_CONTEXT=final || {
            ownership_fail 'retirement evidence publication context failed'
            return 1
        }
    fi
    if ! temporary=$(_evidence_temp "$output"); then
        unset AVELREN_RETIREMENT_PUBLISH_CONTEXT || true
        ownership_fail 'retirement evidence temporary file creation failed'
        return 1
    fi
    if ! unset AVELREN_RETIREMENT_PUBLISH_CONTEXT; then
        rm -f "$temporary"
        ownership_fail 'retirement evidence publication context cleanup failed'
        return 1
    fi
    {
        printf 'exact_commit=%s\n' "$exact_commit"
        printf '%s\n' 'stage=legacy_retired'
        printf 'target_fingerprint=%s\n' "$target_fingerprint"
        printf 'post_retirement_fingerprint=%s\n' "$post_fingerprint"
        printf '%s\n' \
            'legacy_credential_retired=PASS' \
            'privilege_contract_result=PASS' \
            'environment_isolation_result=PASS' \
            'accepted_soak=PASS'
    } >"$temporary" || {
        rm -f "$temporary"
        ownership_fail 'retirement evidence generation failed'
        return 1
    }
    if ! _publish_evidence_file "$temporary" "$output"; then
        rm -f "$temporary" "$output"
        ownership_fail 'retirement evidence publication failed'
        return 1
    fi
}

execute_committed_adoption() {
    local dsn=$1 manifest=$2 forward=$3 evidence_dir=$4 driver output target_manifest
    ADOPTION_FORWARD_COMMITTED=false
    export ADOPTION_COMMITTED_MARKER_PUBLISHED=false
    if ! driver=$(_evidence_temp "$evidence_dir/committed-forward.sql"); then
        ownership_fail 'committed forward driver temporary file creation failed'
        return 1
    fi
    if ! output=$(_evidence_temp "$evidence_dir/committed-forward.marker"); then
        rm -f "$driver"
        ownership_fail 'committed forward marker temporary file creation failed'
        return 1
    fi
    {
        printf '%s\n' '\set ON_ERROR_STOP on' 'BEGIN;'
        cat "$forward"
        _target_ownership_sql "$manifest"
        printf '%s\n' "SELECT 'FORWARD_TARGET_VERIFIED';" 'COMMIT;'
    } >"$driver" || {
        rm -f "$driver" "$output"
        ownership_fail 'committed forward driver generation failed'
        return 1
    }
    if ! _adoption_psql "$dsn" <"$driver" >"$output"; then
        rm -f "$driver" "$output"
        ownership_fail 'committed forward adoption failed'
        return 1
    fi
    export ADOPTION_FORWARD_COMMITTED=true
    if [ "${AVELREN_ADOPTION_COMMITTED_FAILPOINT:-}" = cleanup ]; then
        ownership_fail 'committed forward driver cleanup failed after commit (injected)'
        return 1
    fi
    if ! rm -f "$driver"; then
        rm -f "$output"
        ownership_fail 'committed forward driver cleanup failed after commit'
        return 1
    fi
    grep -Fxq 'FORWARD_TARGET_VERIFIED' "$output" || {
        rm -f "$output"
        ownership_fail 'committed forward target verification was not proven'
        return 1
    }
    if ! _publish_evidence_file "$output" "$evidence_dir/committed-forward.marker"; then
        ownership_fail 'committed forward marker publication failed after commit'
        return 1
    fi
    export ADOPTION_COMMITTED_MARKER_PUBLISHED=true
    case "${AVELREN_ADOPTION_COMMITTED_FAILPOINT:-}" in
        signal_hup) kill -s HUP "$$" ;;
        signal_int) kill -s INT "$$" ;;
        signal_term) kill -s TERM "$$" ;;
    esac
    if [ "${AVELREN_ADOPTION_COMMITTED_FAILPOINT:-}" = capture ]; then
        ownership_fail 'post-commit capture FAIL (injected)'
        return 1
    fi
    target_manifest="$evidence_dir/committed.tsv"
    capture_manifest "$dsn" "$target_manifest" || {
        ownership_fail 'committed forward manifest capture failed after commit'
        return 1
    }
    if [ "${AVELREN_ADOPTION_COMMITTED_FAILPOINT:-}" = verification ]; then
        ownership_fail 'post-commit verification FAIL (injected)'
        return 1
    fi
    verify_target_ownership "$dsn" "$manifest" || {
        ownership_fail 'committed forward target verification failed after commit'
        return 1
    }
}

execute_inverse_rollback() {
    local dsn=$1 manifest=$2 inverse=$3 evidence_dir=$4 driver output status before after corruption
    corruption=${AVELREN_ADOPTION_CORRUPT_INVERSE:-0}
    if ! driver=$(_evidence_temp "$evidence_dir/inverse-rollback.sql"); then
        ownership_fail 'inverse rollback driver temporary file creation failed'
        return 1
    fi
    if ! output=$(_evidence_temp "$evidence_dir/inverse-rollback.marker"); then
        rm -f "$driver"
        ownership_fail 'inverse rollback marker temporary file creation failed'
        return 1
    fi
    {
        printf '%s\n' '\set ON_ERROR_STOP on' 'BEGIN;'
        if [ "$corruption" = incomplete ]; then
            [ "${AVELREN_TEST_DB:-}" = 1 ] || ownership_fail 'corrupt inverse injection is test-only'
            awk 'NF && $0 !~ /^--/ { print; exit }' "$inverse"
        else
            cat "$inverse"
        fi
        if [ "$corruption" = 1 ] || [ "$corruption" = invalid_sql ]; then
            [ "${AVELREN_TEST_DB:-}" = 1 ] || ownership_fail 'corrupt inverse injection is test-only'
            printf '%s\n' 'THIS_IS_AN_INTENTIONALLY_INVALID_INVERSE_STATEMENT;'
        fi
        cat <<'SQL'
CREATE TEMP TABLE avelren_expected_manifest (
    row_text text NOT NULL
) ON COMMIT DROP;
COPY avelren_expected_manifest (row_text) FROM STDIN
WITH (FORMAT csv, DELIMITER E'\x01', QUOTE E'\x02', ESCAPE E'\x02');
SQL
        cat "$manifest"
        printf '%s\n' '\.'
        cat <<'SQL'
CREATE TEMP TABLE avelren_actual_manifest (
    row_text text NOT NULL
) ON COMMIT DROP;
SQL
        _manifest_sql actual_table
        cat <<'SQL'
DO $avelren_inverse_exact_verify$
DECLARE
    mismatch_count bigint;
    mismatch_detail text;
BEGIN
    WITH mismatch AS (
        (SELECT 'EXPECTED_ONLY'::text AS side, row_text
           FROM (SELECT row_text FROM avelren_expected_manifest
                 EXCEPT ALL
                 SELECT row_text FROM avelren_actual_manifest) AS expected_only)
        UNION ALL
        (SELECT 'ACTUAL_ONLY'::text AS side, row_text
           FROM (SELECT row_text FROM avelren_actual_manifest
                 EXCEPT ALL
                 SELECT row_text FROM avelren_expected_manifest) AS actual_only)
    )
    SELECT count(*), string_agg(side || ' | ' || row_text, chr(10) ORDER BY side, row_text)
      INTO mismatch_count, mismatch_detail
      FROM mismatch;
    IF mismatch_count <> 0 THEN
        RAISE EXCEPTION 'inverse rollback exact manifest mismatch (% rows)%',
            mismatch_count, chr(10) || mismatch_detail;
    END IF;
END
$avelren_inverse_exact_verify$;
SELECT 'INVERSE_APPLIED';
COMMIT;
SQL
    } >"$driver" || {
        rm -f "$driver" "$output"
        ownership_fail 'inverse rollback driver generation failed'
        return 1
    }
    set +e
    _adoption_psql "$dsn" <"$driver" >"$output"
    status=$?
    set -e
    if ! rm -f "$driver"; then
        rm -f "$output"
        ownership_fail 'inverse rollback driver cleanup failed after commit'
        return 1
    fi
    if [ "$status" -ne 0 ] || ! grep -Fxq 'INVERSE_APPLIED' "$output"; then
        rm -f "$output"
        ownership_fail 'inverse rollback transaction failed'
        return 1
    fi
    if ! _publish_evidence_file "$output" "$evidence_dir/inverse-rollback.marker"; then
        ownership_fail 'inverse rollback marker publication failed'
        return 1
    fi
    if ! capture_manifest "$dsn" "$evidence_dir/after-failure.tsv"; then
        ownership_fail 'inverse rollback manifest recapture failed'
        return 1
    fi
    if ! before=$(manifest_fingerprint "$manifest"); then
        ownership_fail 'original manifest fingerprint calculation failed during inverse rollback'
        return 1
    fi
    if ! after=$(manifest_fingerprint "$evidence_dir/after-failure.tsv"); then
        ownership_fail 'restored manifest fingerprint calculation failed during inverse rollback'
        return 1
    fi
    if ! publish_manifest_fingerprint "$manifest" "$evidence_dir/original.sha256"; then
        ownership_fail 'original manifest fingerprint evidence publication failed during inverse rollback'
        return 1
    fi
    if ! publish_manifest_fingerprint "$evidence_dir/after-failure.tsv" \
        "$evidence_dir/after-failure.sha256"; then
        ownership_fail 'restored manifest fingerprint evidence publication failed during inverse rollback'
        return 1
    fi
    cmp -s "$manifest" "$evidence_dir/after-failure.tsv" || {
        ownership_fail 'inverse rollback manifest mismatch'
        return 1
    }
    [ "$before" = "$after" ] || {
        ownership_fail 'inverse rollback fingerprint mismatch'
        return 1
    }
}
