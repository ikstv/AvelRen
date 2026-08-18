#!/usr/bin/env bash
# Source-only restore engine. Public CLI policy lives in restore.sh;
# production orchestration lives in restore-production.sh.

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "DENIED: restore engine is source-only" >&2
    exit 2
fi

avelren_restore_engine() {
    local dump=$1 target=$2 stack_dir=$3 compose_file=$4 compose_project=$5 db_service=$6
    local admin_db_user=${AVELREN_ADMIN_DB_USER:-avelren_admin}
    local admin_db_password=${AVELREN_ADMIN_PASSWORD:-}
    declare -g AVELREN_RESTORE_POST_PENDING=false
    declare -g AVELREN_RESTORE_TARGET="$target"
    declare -g AVELREN_RESTORE_COMPOSE_FILE="$compose_file"
    declare -g AVELREN_RESTORE_COMPOSE_PROJECT="$compose_project"
    declare -g AVELREN_RESTORE_DB_SERVICE="$db_service"
    declare -g AVELREN_RESTORE_ADMIN_DB_USER="$admin_db_user"
    declare -g AVELREN_RESTORE_ADMIN_DB_PASSWORD="$admin_db_password"

    case "$target" in
        restore_test|avelren) ;;
        *) echo "DENIED: unsupported restore target: $target" >&2; return 2 ;;
    esac

    [ "$admin_db_user" = avelren_admin ] || {
        echo "restore database role must be avelren_admin" >&2
        return 2
    }
    [ -n "$admin_db_password" ] || {
        echo "restore database password is required" >&2
        return 2
    }

    cd "$stack_dir"
    restore_compose() {
        local args=(docker compose)
        [ -z "$AVELREN_RESTORE_COMPOSE_FILE" ] || args+=(-f "$AVELREN_RESTORE_COMPOSE_FILE")
        [ -z "$AVELREN_RESTORE_COMPOSE_PROJECT" ] || args+=(-p "$AVELREN_RESTORE_COMPOSE_PROJECT")
        "${args[@]}" "$@"
    }
    restore_db_tool() {
        PGPASSWORD="$AVELREN_RESTORE_ADMIN_DB_PASSWORD" restore_compose exec -T -e PGPASSWORD \
            "$AVELREN_RESTORE_DB_SERVICE" "$@"
    }
    restore_psql() {
        restore_db_tool psql -U "$AVELREN_RESTORE_ADMIN_DB_USER" -v ON_ERROR_STOP=1 "$@"
    }
    # NOTE: both `expected(...)` blocks below hardcode the list of application
    # relations. If you add a table/sequence in a migration, update BOTH blocks,
    # otherwise production-restore will fail right after dropdb. Drift is caught in CI by
    # deploy/restore-allowlist-contract-test.py (which checks against schema_verify._TABLES_V).
    restore_application_owners() {
        restore_psql -d "$AVELREN_RESTORE_TARGET" -q <<'SQL'
DO $$
DECLARE
    inventory_mismatch text;
BEGIN
    WITH expected(schema_name, relation_name, relation_kind) AS (
        VALUES
            ('public', 'countries', 'r'),
            ('public', 'checkpoints', 'r'),
            ('public', 'observations', 'r'),
            ('public', 'observations_hourly', 'v'),
            ('public', 'collector_runs', 'r'),
            ('public', 'devices', 'r'),
            ('public', 'subscriptions', 'r'),
            ('public', 'subscription_state', 'r'),
            ('public', 'alerts', 'r'),
            ('public', 'eta_targets', 'r'),
            ('public', 'eta_alerts', 'r'),
            ('public', 'health_alerts', 'r'),
            ('public', 'notification_cancels', 'r'),
            ('public', 'schema_migrations', 'r'),
            ('public', 'alerts_id_seq', 'S'),
            ('public', 'eta_alerts_id_seq', 'S'),
            ('public', 'health_alerts_id_seq', 'S'),
            ('public', 'notification_cancels_id_seq', 'S'),
            ('public', 'subscriptions_id_seq', 'S'),
            ('public', 'eta_targets_id_seq', 'S')
    ),
    actual AS (
        SELECT namespace.nspname::text AS schema_name,
               relation.relname::text AS relation_name,
               relation.relkind::text AS relation_kind
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND relation.relkind IN ('r', 'p', 'S', 'v', 'm')
          AND NOT EXISTS (
              SELECT 1
              FROM pg_depend AS dependency
              JOIN pg_extension AS extension
                ON extension.oid = dependency.refobjid
              WHERE dependency.classid = 'pg_class'::regclass
                AND dependency.objid = relation.oid
                AND dependency.refclassid = 'pg_extension'::regclass
                AND dependency.deptype = 'e'
                AND extension.extname = 'timescaledb'
          )
    ),
    mismatch AS (
        SELECT 'missing'::text AS issue, missing.*
        FROM (
            SELECT expected.* FROM expected
            EXCEPT
            SELECT actual.* FROM actual
        ) AS missing
        UNION ALL
        SELECT 'unexpected'::text AS issue, unexpected.*
        FROM (
            SELECT actual.* FROM actual
            EXCEPT
            SELECT expected.* FROM expected
        ) AS unexpected
    )
    SELECT string_agg(
               format('%s %I.%I (%s)', issue, schema_name, relation_name, relation_kind),
               ', ' ORDER BY issue, schema_name, relation_name, relation_kind
           )
    INTO inventory_mismatch
    FROM mismatch;

    IF inventory_mismatch IS NOT NULL THEN
        RAISE EXCEPTION 'restore application relation allowlist mismatch: %',
            inventory_mismatch;
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        JOIN pg_roles AS owner ON owner.oid = relation.relowner
        WHERE namespace.nspname = 'public'
          AND relation.relkind IN ('r', 'p', 'S', 'v', 'm')
          AND NOT EXISTS (
              SELECT 1
              FROM pg_depend AS dependency
              JOIN pg_extension AS extension
                ON extension.oid = dependency.refobjid
              WHERE dependency.classid = 'pg_class'::regclass
                AND dependency.objid = relation.oid
                AND dependency.refclassid = 'pg_extension'::regclass
                AND dependency.deptype = 'e'
                AND extension.extname = 'timescaledb'
          )
          AND owner.rolname <> 'avelren_admin'
    ) THEN
        RAISE EXCEPTION 'restored application relations must be owned by avelren_admin before handoff';
    END IF;
    IF (SELECT owner.rolname
        FROM pg_extension AS extension
        JOIN pg_roles AS owner ON owner.oid = extension.extowner
        WHERE extension.extname = 'timescaledb') <> 'avelren_admin' THEN
        RAISE EXCEPTION 'timescaledb extension owner must remain avelren_admin';
    END IF;
END
$$;

WITH expected(schema_name, relation_name, relation_kind) AS (
    VALUES
        ('public', 'countries', 'r'),
        ('public', 'checkpoints', 'r'),
        ('public', 'observations', 'r'),
        ('public', 'observations_hourly', 'v'),
        ('public', 'collector_runs', 'r'),
        ('public', 'devices', 'r'),
        ('public', 'subscriptions', 'r'),
        ('public', 'subscription_state', 'r'),
        ('public', 'alerts', 'r'),
        ('public', 'eta_targets', 'r'),
        ('public', 'eta_alerts', 'r'),
        ('public', 'health_alerts', 'r'),
        ('public', 'notification_cancels', 'r'),
        ('public', 'schema_migrations', 'r'),
        ('public', 'alerts_id_seq', 'S'),
        ('public', 'eta_alerts_id_seq', 'S'),
        ('public', 'health_alerts_id_seq', 'S'),
        ('public', 'notification_cancels_id_seq', 'S'),
        ('public', 'subscriptions_id_seq', 'S'),
        ('public', 'eta_targets_id_seq', 'S')
)
SELECT format(
    'ALTER %s %I.%I OWNER TO avelren_migrator',
    CASE
        WHEN relation.relname = 'observations_hourly' THEN 'MATERIALIZED VIEW'
        WHEN relation.relkind = 'S' THEN 'SEQUENCE'
        WHEN relation.relkind = 'v' THEN 'VIEW'
        WHEN relation.relkind = 'm' THEN 'MATERIALIZED VIEW'
        ELSE 'TABLE'
    END,
    namespace.nspname,
    relation.relname
)
FROM pg_class AS relation
JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
JOIN expected
  ON expected.schema_name = namespace.nspname
 AND expected.relation_name = relation.relname
 AND expected.relation_kind = relation.relkind::text
ORDER BY CASE relation.relkind WHEN 'S' THEN 2 ELSE 1 END, relation.relname
\gexec

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        JOIN pg_roles AS owner ON owner.oid = relation.relowner
        WHERE namespace.nspname = 'public'
          AND relation.relkind IN ('r', 'p', 'S', 'v', 'm')
          AND NOT EXISTS (
              SELECT 1
              FROM pg_depend AS dependency
              JOIN pg_extension AS extension
                ON extension.oid = dependency.refobjid
              WHERE dependency.classid = 'pg_class'::regclass
                AND dependency.objid = relation.oid
                AND dependency.refclassid = 'pg_extension'::regclass
                AND dependency.deptype = 'e'
                AND extension.extname = 'timescaledb'
          )
          AND owner.rolname <> 'avelren_migrator'
    ) THEN
        RAISE EXCEPTION 'restore application ownership finalization failed';
    END IF;
END
$$;
SQL
    }
    restore_log() { echo "$(date -u +%FT%TZ) $*"; }

    # Invoked by the EXIT trap below.
    # shellcheck disable=SC2329
    restore_finalize() {
        local primary_status=$?
        trap - EXIT
        if [ "$AVELREN_RESTORE_POST_PENDING" = true ]; then
            set +e
            restore_log "primary restore failure (exit=$primary_status); attempting timescaledb_post_restore"
            restore_psql -d "$AVELREN_RESTORE_TARGET" -q -c "SELECT timescaledb_post_restore();"
            local cleanup_status=$?
            if [ "$cleanup_status" -eq 0 ]; then
                restore_log "timescaledb_post_restore cleanup succeeded after primary failure"
            else
                restore_log "ERROR: primary restore failed (exit=$primary_status) and timescaledb_post_restore cleanup failed (exit=$cleanup_status)"
            fi
        fi
        exit "$primary_status"
    }
    trap restore_finalize EXIT

    restore_log "preparing database $target"
    restore_db_tool dropdb --if-exists --maintenance-db=postgres \
        -U "$AVELREN_RESTORE_ADMIN_DB_USER" "$target"
    restore_db_tool createdb --maintenance-db=postgres \
        -U "$AVELREN_RESTORE_ADMIN_DB_USER" "$target"
    restore_psql -d "$target" -q -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"

    restore_log "timescaledb_pre_restore"
    restore_psql -d "$target" -q -c "SELECT timescaledb_pre_restore();"
    AVELREN_RESTORE_POST_PENDING=true

    restore_log "restoring data"
    gunzip -c "$dump" | restore_psql -d "$target" -q -v ON_ERROR_STOP=1

    restore_log "timescaledb_post_restore"
    set +e
    restore_psql -d "$target" -q -c "SELECT timescaledb_post_restore();"
    local post_status=$?
    set -e
    AVELREN_RESTORE_POST_PENDING=false
    if [ "$post_status" -ne 0 ]; then
        restore_log "ERROR: timescaledb_post_restore failed (exit=$post_status)"
        exit "$post_status"
    fi

    restore_log "application ownership finalization"
    restore_application_owners

    restore_log "verification"
    restore_psql -d "$target" -c "
SELECT (SELECT count(*) FROM observations) AS observations,
       (SELECT count(*) FROM checkpoints) AS checkpoints,
       (SELECT count(*) FROM timescaledb_information.hypertables) AS hypertables,
       (SELECT count(*) FROM timescaledb_information.continuous_aggregates) AS aggregates;"
    restore_log "done: database $target"
}
