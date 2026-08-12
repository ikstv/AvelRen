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
database_created_this_invocation=0

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

# roles-acl reassigns ownership and rewrites ACLs of an already existing
# database. That is the same class of mutation as adoption, so it carries the
# same disposable-only boundary as deploy/postgres-adopt.sh: production ownership
# and ACL changes are performed exclusively through the adoption path, which
# proves preflight evidence, forward/inverse plans and fingerprints first.
if [ "$mode" = roles-acl ]; then
    [ "${AVELREN_TEST_DB:-}" = 1 ] || fail 'roles-acl execution is disposable-only'
    case "$DB_NAME" in *test*|*ci*) ;;
        *) fail 'disposable target name must contain test or ci' ;;
    esac
fi

admin_psql_maintenance() {
    PGPASSWORD="$AVELREN_ADMIN_PASSWORD" psql -X -v ON_ERROR_STOP=1 \
        --dbname="$AVELREN_ADMIN_DSN" "$@"
}

admin_psql_target() {
    PGPASSWORD="$AVELREN_ADMIN_PASSWORD" psql -X --quiet -v ON_ERROR_STOP=1 \
        --dbname="$AVELREN_ADMIN_DSN" --set=target_db_name="$DB_NAME" "$@"
}

database_exists() {
    admin_psql_maintenance --set=bootstrap_stage=database_exists --set=db_name="$DB_NAME" \
        --tuples-only --no-align <<'SQL'
-- bootstrap-stage:database-exists
SELECT EXISTS (SELECT FROM pg_database WHERE datname = :'db_name');
SQL
}

database_is_disposable_empty() {
    admin_psql_target --set=bootstrap_stage=cleanup --tuples-only --no-align <<'SQL'
-- bootstrap-stage:cleanup
\connect :target_db_name
-- bootstrap-cleanup:disposable-empty
SELECT
    (SELECT database.datallowconn
     FROM pg_database AS database
     WHERE database.datname = current_database())
    AND NOT (SELECT database.datistemplate
             FROM pg_database AS database
             WHERE database.datname = current_database())
    AND (SELECT database.datconnlimit
         FROM pg_database AS database
         WHERE database.datname = current_database()) = -1
    AND (SELECT database.datacl IS NULL
         FROM pg_database AS database
         WHERE database.datname = current_database())
    AND (SELECT owner.rolname
         FROM pg_database AS database
         JOIN pg_roles AS owner ON owner.oid = database.datdba
         WHERE database.datname = current_database()) = 'avelren_admin'
    AND (SELECT database.dattablespace
         FROM pg_database AS database
         WHERE database.datname = current_database()) = 0
    AND NOT EXISTS (
        SELECT 1
        FROM pg_db_role_setting AS setting
        JOIN pg_database AS database ON database.oid = setting.setdatabase
        WHERE database.datname = current_database()
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_shdescription AS description
        JOIN pg_database AS database ON database.oid = description.objoid
        WHERE description.classoid = 'pg_database'::regclass
          AND database.datname = current_database()
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_stat_activity AS activity
        WHERE activity.datname = current_database()
          AND activity.pid <> pg_backend_pid()
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_namespace AS namespace
        WHERE namespace.nspname NOT IN ('pg_catalog', 'information_schema', 'public')
          AND namespace.nspname <> 'pg_toast'
          AND namespace.nspname NOT LIKE 'pg_toast_temp_%'
          AND namespace.nspname NOT LIKE 'pg_temp_%'
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname NOT IN ('pg_catalog', 'information_schema')
          AND namespace.nspname <> 'pg_toast'
          AND namespace.nspname NOT LIKE 'pg_toast_temp_%'
          AND namespace.nspname NOT LIKE 'pg_temp_%'
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_proc AS routine
        JOIN pg_namespace AS namespace ON namespace.oid = routine.pronamespace
        WHERE namespace.nspname NOT IN ('pg_catalog', 'information_schema')
          AND namespace.nspname <> 'pg_toast'
          AND namespace.nspname NOT LIKE 'pg_toast_temp_%'
          AND namespace.nspname NOT LIKE 'pg_temp_%'
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_type AS type
        JOIN pg_namespace AS namespace ON namespace.oid = type.typnamespace
        WHERE namespace.nspname NOT IN ('pg_catalog', 'information_schema')
          AND namespace.nspname <> 'pg_toast'
          AND namespace.nspname NOT LIKE 'pg_toast_temp_%'
          AND namespace.nspname NOT LIKE 'pg_temp_%'
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_collation AS collation
        JOIN pg_namespace AS namespace ON namespace.oid = collation.collnamespace
        WHERE namespace.nspname NOT IN ('pg_catalog', 'information_schema')
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_conversion AS conversion
        JOIN pg_namespace AS namespace ON namespace.oid = conversion.connamespace
        WHERE namespace.nspname NOT IN ('pg_catalog', 'information_schema')
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_operator AS operator
        JOIN pg_namespace AS namespace ON namespace.oid = operator.oprnamespace
        WHERE namespace.nspname NOT IN ('pg_catalog', 'information_schema')
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_opclass AS opclass
        JOIN pg_namespace AS namespace ON namespace.oid = opclass.opcnamespace
        WHERE namespace.nspname NOT IN ('pg_catalog', 'information_schema')
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_opfamily AS opfamily
        JOIN pg_namespace AS namespace ON namespace.oid = opfamily.opfnamespace
        WHERE namespace.nspname NOT IN ('pg_catalog', 'information_schema')
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_ts_config AS configuration
        JOIN pg_namespace AS namespace ON namespace.oid = configuration.cfgnamespace
        WHERE namespace.nspname NOT IN ('pg_catalog', 'information_schema')
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_ts_dict AS dictionary
        JOIN pg_namespace AS namespace ON namespace.oid = dictionary.dictnamespace
        WHERE namespace.nspname NOT IN ('pg_catalog', 'information_schema')
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_ts_parser AS parser
        JOIN pg_namespace AS namespace ON namespace.oid = parser.prsnamespace
        WHERE namespace.nspname NOT IN ('pg_catalog', 'information_schema')
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_ts_template AS template
        JOIN pg_namespace AS namespace ON namespace.oid = template.tmplnamespace
        WHERE namespace.nspname NOT IN ('pg_catalog', 'information_schema')
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_statistic_ext AS statistic
        JOIN pg_namespace AS namespace ON namespace.oid = statistic.stxnamespace
        WHERE namespace.nspname NOT IN ('pg_catalog', 'information_schema')
    )
    AND NOT EXISTS (SELECT 1 FROM pg_largeobject_metadata)
    AND NOT EXISTS (SELECT 1 FROM pg_default_acl)
    AND NOT EXISTS (SELECT 1 FROM pg_event_trigger)
    AND NOT EXISTS (SELECT 1 FROM pg_foreign_data_wrapper)
    AND NOT EXISTS (SELECT 1 FROM pg_foreign_server)
    AND NOT EXISTS (SELECT 1 FROM pg_publication)
    AND NOT EXISTS (SELECT 1 FROM pg_subscription)
    AND EXISTS (
        SELECT 1
        FROM pg_extension AS extension
        JOIN pg_namespace AS namespace ON namespace.oid = extension.extnamespace
        WHERE extension.extname = 'plpgsql'
          AND namespace.nspname = 'pg_catalog'
    )
    AND NOT EXISTS (
        SELECT 1
        FROM pg_extension AS extension
        JOIN pg_namespace AS namespace ON namespace.oid = extension.extnamespace
        WHERE extension.extname <> 'plpgsql'
           OR namespace.nspname <> 'pg_catalog'
    );
SQL
}

cleanup_disposable_empty_test() {
    local empty
    [ "$database_created_this_invocation" -eq 1 ] || fail 'cleanup requires a database created by this invocation'
    [[ "$DB_NAME" == *_test ]] || fail 'cleanup requires a *_test database name'
    [ "${AVELREN_TEST_DB:-}" = 1 ] || fail 'cleanup requires AVELREN_TEST_DB=1'
    if ! empty=$(database_is_disposable_empty); then
        fail 'cleanup could not prove a newly created, disposable empty target database'
    fi
    [ "$empty" = t ] || fail 'cleanup requires a newly created, disposable empty target database'
    admin_psql_maintenance --set=bootstrap_stage=cleanup --set=db_name="$DB_NAME" <<'SQL'
-- bootstrap-stage:cleanup
-- bootstrap-cleanup:drop
SELECT format('DROP DATABASE %I', :'db_name') \gexec
SQL
}

create_roles() {
    admin_psql_maintenance -f "$ROOT/db/security/bootstrap.sql"
}

# Fail-closed guard проти privilege-escalation через role membership.
#
# Canonical-граф не має ЖОДНОГО membership між avelren_%-ролями (bootstrap.sql
# явно REVOKE'ає admin/migrator memberships — це known-safe baseline). Будь-який
# ЗАЛИШКОВИЙ avelren_% → avelren_% membership (напр. хтось видав
# `GRANT avelren_collector TO avelren_api`, і api через SET ROLE отримав чужі
# права) — це неочікувана ескалація, яку bootstrap НЕ виправляє мовчки:
# автоматичний REVOKE приховав би факт компрометації. Замість цього — halt із
# явним повідомленням, щоб адміністратор розслідував походження membership'а і
# зняв його свідомо (саме так робить інтеграційний тест: спершу бачить fail,
# потім REVOKE руками адміна, потім повторний bootstrap проходить).
#
# Запускається ПІСЛЯ create_roles: baseline-revoke'и bootstrap.sql уже
# застосовані, тож у чистому стані лишається 0 memberships, і guard мовчить.
verify_role_memberships() {
    local forbidden
    if ! forbidden=$(admin_psql_maintenance --set=bootstrap_stage=verify_memberships \
        --tuples-only --no-align <<'SQL'
-- bootstrap-stage:verify_memberships
SELECT count(*)
FROM pg_auth_members AS membership
JOIN pg_roles AS granted_role ON granted_role.oid = membership.roleid
JOIN pg_roles AS member_role ON member_role.oid = membership.member
WHERE granted_role.rolname LIKE 'avelren_%'
   OR member_role.rolname LIKE 'avelren_%';
SQL
    ); then
        fail 'could not verify canonical role memberships'
    fi
    case "$forbidden" in
        0) return 0 ;;
        [1-9]*) fail 'forbidden canonical role membership detected' ;;
        *) fail 'canonical role membership query returned an unexpected result' ;;
    esac
}

create_database() {
    local exists
    if ! exists=$(database_exists); then
        fail 'could not verify whether the target database already exists'
    fi
    case "$exists" in
        t) return 0 ;;
        f) ;;
        *) fail 'database existence query returned an unexpected result' ;;
    esac
    admin_psql_maintenance --set=bootstrap_stage=create_database --set=db_name="$DB_NAME" <<'SQL'
-- bootstrap-stage:create_database
SELECT format('CREATE DATABASE %I OWNER avelren_admin', :'db_name') \gexec
SQL
    database_created_this_invocation=1
}

provision_extension() {
    admin_psql_target --set=bootstrap_stage=extension <<'SQL'
-- bootstrap-stage:extension
\connect :target_db_name
CREATE EXTENSION IF NOT EXISTS timescaledb WITH SCHEMA public;
SQL
}

apply_acl() {
    admin_psql_target --set=bootstrap_stage=acl <<'SQL'
-- bootstrap-stage:acl
\connect :target_db_name
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
\connect :target_db_name
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

cleanup_after_failed_fresh() {
    local status=$?
    trap - EXIT
    if [ "$status" -ne 0 ] && [ "$cleanup_requested" -eq 1 ] && \
       [ "$database_created_this_invocation" -eq 1 ]; then
        if ! ( cleanup_disposable_empty_test ); then
            printf 'postgres bootstrap: cleanup after failed fresh bootstrap was refused\n' >&2
        fi
    fi
    exit "$status"
}

if [ "$mode" = fresh ] && [ "$cleanup_requested" -eq 1 ]; then
    trap cleanup_after_failed_fresh EXIT
fi
create_roles
verify_role_memberships
if [ "$mode" = fresh ]; then
    create_database
    provision_extension
fi
apply_acl
verify_owners

if [ "$mode" = fresh ]; then
    printf 'migrate_handoff\n'
fi
printf 'postgres bootstrap complete: %s\n' "$mode"
