#!/usr/bin/env bash
# Source-only, read-only composition gate for a future production restore.

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "DENIED: production restore preflight is source-only" >&2
    exit 2
fi

_AVELREN_PREFLIGHT_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=ops/restore-artifact.lib.sh
source "$_AVELREN_PREFLIGHT_DIR/restore-artifact.lib.sh"
# shellcheck source=ops/restore-production-identity.lib.sh
source "$_AVELREN_PREFLIGHT_DIR/restore-production-identity.lib.sh"

_avelren_preflight_sql() {
    local category=${1:?preflight SQL category is required}
    local sql result
    sql=$(cat)
    if ! result=$(
        PGPASSWORD="$AVELREN_ADMIN_PASSWORD" \
        PGOPTIONS='-c default_transaction_read_only=on' \
        AVELREN_EXPECTED_JOURNAL="$AVELREN_EXPECTED_JOURNAL" \
        docker compose \
          --project-directory /opt/avelren \
          --env-file /opt/avelren/.env \
          -f /opt/avelren/docker-compose.yml \
          -p avelren \
          exec -T -e PGPASSWORD -e PGOPTIONS -e AVELREN_EXPECTED_JOURNAL db \
          psql -X -v ON_ERROR_STOP=1 -At -U avelren_admin -d avelren <<<"$sql"
    ); then
        echo "DENIED: production database $category check failed" >&2
        return 1
    fi
    if [ "$result" != t ]; then
        echo "DENIED: production database $category check was not satisfied" >&2
        return 1
    fi
}

avelren_verify_production_database_journal() {
    _avelren_preflight_sql identity-and-journal <<'SQL'
-- preflight:database
\getenv expected_journal AVELREN_EXPECTED_JOURNAL
SELECT (
    current_database() = 'avelren'
    AND current_user = 'avelren_admin'
    AND COALESCE(
        (SELECT jsonb_object_agg(version, sha256 ORDER BY version) FROM public.schema_migrations),
        '{}'::jsonb
    ) = :'expected_journal'::jsonb
);
SQL
}

avelren_verify_production_roles_owners_grants() {
    _avelren_preflight_sql roles-owners-and-grants <<'SQL'
-- preflight:roles-and-grants
WITH expected(role_name, can_login, is_superuser) AS (
    VALUES
      ('avelren_admin', true, true),
      ('avelren_migrator', true, false),
      ('avelren_backup', true, false),
      ('avelren_collector', true, false),
      ('avelren_notifier', true, false),
      ('avelren_watchdog', true, false),
      ('avelren_api', true, false)
), canonical AS (
    SELECT role.oid, role.rolname, role.rolcanlogin, role.rolsuper,
           role.rolcreatedb, role.rolcreaterole, role.rolreplication, role.rolbypassrls
    FROM pg_roles AS role
    WHERE role.rolname LIKE 'avelren\_%' ESCAPE '\'
), application_relations AS (
    SELECT relation.oid, owner.rolname AS owner_name, relation.relkind
    FROM pg_class AS relation
    JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
    JOIN pg_roles AS owner ON owner.oid = relation.relowner
    WHERE namespace.nspname = 'public'
      AND relation.relkind IN ('r', 'p', 'S', 'v', 'm')
      AND NOT EXISTS (
          SELECT 1 FROM pg_depend AS dependency
          JOIN pg_extension AS extension ON extension.oid = dependency.refobjid
          WHERE dependency.classid = 'pg_class'::regclass
            AND dependency.objid = relation.oid
            AND dependency.refclassid = 'pg_extension'::regclass
            AND dependency.deptype = 'e'
            AND extension.extname = 'timescaledb'
      )
)
SELECT (
    NOT EXISTS (
        SELECT role_name, can_login, is_superuser FROM expected
        EXCEPT SELECT rolname, rolcanlogin, rolsuper FROM canonical
    )
    AND NOT EXISTS (
        SELECT rolname, rolcanlogin, rolsuper FROM canonical
        EXCEPT SELECT role_name, can_login, is_superuser FROM expected
    )
    AND NOT EXISTS (
        SELECT 1 FROM canonical
        WHERE rolname <> 'avelren_admin'
          AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication OR rolbypassrls)
    )
    AND NOT EXISTS (
        SELECT 1 FROM pg_auth_members AS membership
        JOIN pg_roles AS granted ON granted.oid = membership.roleid
        JOIN pg_roles AS member ON member.oid = membership.member
        WHERE granted.rolname LIKE 'avelren\_%' ESCAPE '\'
           OR member.rolname LIKE 'avelren\_%' ESCAPE '\'
    )
    AND (SELECT owner.rolname FROM pg_database AS database
         JOIN pg_roles AS owner ON owner.oid = database.datdba
         WHERE database.datname = current_database()) = 'avelren_admin'
    AND (SELECT owner.rolname FROM pg_namespace AS namespace
         JOIN pg_roles AS owner ON owner.oid = namespace.nspowner
         WHERE namespace.nspname = 'public') = 'avelren_admin'
    AND (SELECT owner.rolname FROM pg_extension AS extension
         JOIN pg_roles AS owner ON owner.oid = extension.extowner
         WHERE extension.extname = 'timescaledb') = 'avelren_admin'
    AND NOT EXISTS (SELECT 1 FROM application_relations WHERE owner_name <> 'avelren_migrator')
    AND NOT EXISTS (
        SELECT 1 FROM expected
        WHERE role_name <> 'avelren_admin'
          AND (has_database_privilege(role_name, current_database(), 'CREATE')
               OR has_database_privilege(role_name, current_database(), 'TEMP')
               OR has_schema_privilege(role_name, 'public', 'CREATE'))
    )
    AND NOT EXISTS (
        SELECT 1 FROM application_relations
        WHERE (relkind = 'S' AND NOT has_sequence_privilege('avelren_backup', oid, 'SELECT'))
           OR (relkind <> 'S' AND NOT has_table_privilege('avelren_backup', oid, 'SELECT'))
    )
);
SQL
}

avelren_verify_production_sessions() {
    _avelren_preflight_sql sessions <<'SQL'
-- preflight:sessions
SELECT (NOT EXISTS (
    SELECT 1
    FROM pg_stat_activity
    WHERE datname = current_database()
      AND pid <> pg_backend_pid()
      AND backend_type = 'client backend'
      AND usename NOT IN ('avelren_api', 'avelren_collector', 'avelren_notifier', 'avelren_watchdog')
));
SQL
}

avelren_verify_production_quiescent_sessions() {
    _avelren_preflight_sql quiescent-sessions <<'SQL'
-- preflight:quiescent-sessions
SELECT (NOT EXISTS (
    SELECT 1
    FROM pg_stat_activity
    WHERE datname = current_database()
      AND pid <> pg_backend_pid()
      AND backend_type = 'client backend'
));
SQL
}

avelren_verify_production_preflight() {
    local dump=${1:?dump path is required}
    local sidecar=${2:?SHA-256 sidecar path is required}
    local evidence=${3:?evidence record is required}
    local source_root=${4:?source root is required}
    local digest ignored metadata
    local -a fields

    unset AVELREN_VERIFIED_TARGET_COMMIT AVELREN_VERIFIED_MIGRATION_PIN \
      AVELREN_VERIFIED_ARTIFACT_SHA AVELREN_EXPECTED_JOURNAL
    [ -n "${AVELREN_ADMIN_PASSWORD:-}" ] || {
        echo "DENIED: production admin password is required through the environment" >&2
        return 1
    }

    avelren_verify_restore_artifact "$dump" "$sidecar" || return
    avelren_verify_production_compose_identity || return

    read -r digest ignored < <(sha256sum -- "$dump")
    digest=${digest,,}
    [[ "$digest" =~ ^[0-9a-f]{64}$ ]] || {
        echo "DENIED: backup artifact digest could not be determined" >&2
        return 1
    }
    python3 "$_AVELREN_PREFLIGHT_DIR/restore-role-pin.py" verify \
      --record "$evidence" --source-root "$source_root" --dump-sha256 "$digest" \
      >/dev/null || return

    if ! metadata=$(python3 - "$evidence" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    record = json.load(source)
print(record["target_commit"])
print(record["recovery_migration_pin"])
print(json.dumps(record["database_journal"], separators=(",", ":")))
PY
    ); then
        echo "DENIED: validated evidence metadata could not be read" >&2
        return 1
    fi
    mapfile -t fields <<<"$metadata"
    if [ "${#fields[@]}" -ne 3 ] || ! [[ "${fields[0]}" =~ ^[0-9a-f]{40}$ ]] || \
       ! [[ "${fields[1]}" =~ ^[0-9]{3}_[a-z0-9][a-z0-9_]*$ ]] || \
       ! [[ "${fields[2]}" =~ ^\{.*\}$ ]]; then
        echo "DENIED: validated evidence metadata was not sanitised" >&2
        return 1
    fi
    AVELREN_EXPECTED_JOURNAL=${fields[2]}

    avelren_verify_production_database_journal || return
    avelren_verify_production_roles_owners_grants || return
    avelren_verify_production_sessions || return

    export AVELREN_VERIFIED_TARGET_COMMIT=${fields[0]}
    export AVELREN_VERIFIED_MIGRATION_PIN=${fields[1]}
    export AVELREN_VERIFIED_ARTIFACT_SHA=$digest
}
