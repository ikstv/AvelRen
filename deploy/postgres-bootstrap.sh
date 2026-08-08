#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT=$(cd "$(dirname "$0")/.." && pwd)
readonly ROOT

usage() {
    printf 'usage: %s fresh|roles-acl [--disposable-empty-test]\n' "$0" >&2
    exit 2
}

fail() {
    printf 'postgres bootstrap: %s\n' "$*" >&2
    exit 1
}

require_value() {
    local name=$1
    [ -n "${!name:-}" ] || fail "missing required environment variable: $name"
}

mode=${1:-}
case "$mode" in
    fresh|roles-acl) ;;
    *) usage ;;
esac
shift || true

cleanup_requested=0
if [ "${1:-}" = '--disposable-empty-test' ]; then
    cleanup_requested=1
    shift
fi
[ "$#" -eq 0 ] || usage
[ "$cleanup_requested" -eq 0 ] || [ "$mode" = fresh ] || fail 'cleanup is available only for fresh bootstrap'

for variable in \
    AVELREN_ADMIN_DSN \
    AVELREN_ADMIN_PASSWORD \
    AVELREN_MIGRATOR_PASSWORD \
    AVELREN_BACKUP_PASSWORD \
    AVELREN_COLLECTOR_PASSWORD \
    AVELREN_NOTIFIER_PASSWORD \
    AVELREN_WATCHDOG_PASSWORD \
    AVELREN_API_PASSWORD
do
    require_value "$variable"
done

DB_NAME=${AVELREN_DB_NAME:-${POSTGRES_DB:-avelren}}
case "$DB_NAME" in
    [A-Za-z_][A-Za-z0-9_]*) ;;
    *) fail 'AVELREN_DB_NAME must be a PostgreSQL identifier' ;;
esac
[[ "$DB_NAME" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || fail 'AVELREN_DB_NAME must be a PostgreSQL identifier'
if [[ "$DB_NAME" == *_test ]] && [ "${AVELREN_TEST_DB:-}" != 1 ]; then
    fail 'refusing a *_test target without AVELREN_TEST_DB=1'
fi

admin_psql_maintenance() {
    PGPASSWORD="$AVELREN_ADMIN_PASSWORD" psql -X -v ON_ERROR_STOP=1 \
        --dbname="$AVELREN_ADMIN_DSN" "$@"
}

admin_psql_target() {
    PGPASSWORD="$AVELREN_ADMIN_PASSWORD" psql -X -v ON_ERROR_STOP=1 \
        --dbname="$AVELREN_ADMIN_DSN" --dbname="$DB_NAME" "$@"
}

database_exists() {
    admin_psql_maintenance --set=bootstrap_stage=cleanup --set=db_name="$DB_NAME" \
        --tuples-only --no-align <<'SQL'
-- bootstrap-stage:cleanup
SELECT EXISTS (SELECT FROM pg_database WHERE datname = :'db_name');
SQL
}

database_is_empty() {
    admin_psql_target --set=bootstrap_stage=cleanup --tuples-only --no-align <<'SQL'
-- bootstrap-stage:cleanup
SELECT
    NOT EXISTS (
        SELECT 1
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
          AND relation.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_proc AS routine
        JOIN pg_namespace AS namespace ON namespace.oid = routine.pronamespace
        WHERE namespace.nspname = 'public'
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_type AS type
        JOIN pg_namespace AS namespace ON namespace.oid = type.typnamespace
        WHERE namespace.nspname = 'public'
          AND type.typtype IN ('b', 'c', 'd', 'e', 'r')
    );
SQL
}

cleanup_disposable_empty_test() {
    [[ "$DB_NAME" == *_test ]] || fail 'cleanup requires a *_test database name'
    [ "${AVELREN_TEST_DB:-}" = 1 ] || fail 'cleanup requires AVELREN_TEST_DB=1'
    [ "$(database_exists)" = t ] || return 0
    [ "$(database_is_empty)" = t ] || fail 'cleanup requires an empty target database'
    admin_psql_maintenance --set=bootstrap_stage=cleanup --set=db_name="$DB_NAME" <<'SQL'
-- bootstrap-stage:cleanup
SELECT format('DROP DATABASE %I', :'db_name') \gexec
SQL
}

create_roles() {
    admin_psql_maintenance -f "$ROOT/db/security/bootstrap.sql"
}

create_database() {
    admin_psql_maintenance --set=bootstrap_stage=create_database --set=db_name="$DB_NAME" <<'SQL'
-- bootstrap-stage:create_database
SELECT format('CREATE DATABASE %I OWNER avelren_admin', :'db_name')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'db_name')
\gexec
SQL
}

provision_extension() {
    admin_psql_target --set=bootstrap_stage=extension --command \
        'CREATE EXTENSION IF NOT EXISTS timescaledb WITH SCHEMA public;'
}

apply_acl() {
    admin_psql_target --set=bootstrap_stage=acl <<'SQL'
-- bootstrap-stage:acl
SELECT format('ALTER DATABASE %I OWNER TO avelren_admin', current_database()) \gexec
ALTER SCHEMA public OWNER TO avelren_admin;

SELECT format('REVOKE ALL PRIVILEGES ON DATABASE %I FROM PUBLIC', current_database()) \gexec
SELECT format(
    'REVOKE ALL PRIVILEGES ON DATABASE %I FROM avelren_migrator, avelren_backup, avelren_collector, avelren_notifier, avelren_watchdog, avelren_api',
    current_database()
) \gexec
SELECT format(
    'GRANT CONNECT ON DATABASE %I TO avelren_admin, avelren_migrator, avelren_backup, avelren_collector, avelren_notifier, avelren_watchdog, avelren_api',
    current_database()
) \gexec

REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM
    avelren_migrator, avelren_backup, avelren_collector, avelren_notifier,
    avelren_watchdog, avelren_api;
GRANT USAGE ON SCHEMA public TO
    avelren_backup, avelren_collector, avelren_notifier, avelren_watchdog,
    avelren_api;
GRANT USAGE, CREATE ON SCHEMA public TO avelren_migrator;
SQL
}

verify_owners() {
    admin_psql_target --set=bootstrap_stage=verify <<'SQL'
-- bootstrap-stage:verify
DO $$
BEGIN
    IF (SELECT owner.rolname
        FROM pg_database AS database
        JOIN pg_roles AS owner ON owner.oid = database.datdba
        WHERE database.datname = current_database()) <> 'avelren_admin' THEN
        RAISE EXCEPTION 'database owner is not avelren_admin';
    END IF;
    IF (SELECT owner.rolname
        FROM pg_namespace AS namespace
        JOIN pg_roles AS owner ON owner.oid = namespace.nspowner
        WHERE namespace.nspname = 'public') <> 'avelren_admin' THEN
        RAISE EXCEPTION 'public schema owner is not avelren_admin';
    END IF;
    IF (SELECT owner.rolname
        FROM pg_extension AS extension
        JOIN pg_roles AS owner ON owner.oid = extension.extowner
        WHERE extension.extname = 'timescaledb') <> 'avelren_admin' THEN
        RAISE EXCEPTION 'timescaledb owner is not avelren_admin';
    END IF;
END
$$;
SQL
}

create_roles
if [ "$mode" = fresh ]; then
    if [ "$cleanup_requested" -eq 1 ]; then
        cleanup_disposable_empty_test
    fi
    create_database
    provision_extension
fi
apply_acl
verify_owners

if [ "$mode" = fresh ]; then
    printf 'migrate_handoff\n'
fi
printf 'postgres bootstrap complete: %s\n' "$mode"
