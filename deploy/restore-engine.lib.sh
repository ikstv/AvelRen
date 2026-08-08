#!/usr/bin/env bash
# Source-only restore engine. Public CLI policy lives in restore.sh;
# production orchestration lives in restore-production.sh.

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "ВІДМОВА: restore engine is source-only" >&2
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
        *) echo "ВІДМОВА: unsupported restore target: $target" >&2; return 2 ;;
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
                restore_log "ПОМИЛКА: primary restore failed (exit=$primary_status) and timescaledb_post_restore cleanup failed (exit=$cleanup_status)"
            fi
        fi
        exit "$primary_status"
    }
    trap restore_finalize EXIT

    restore_log "готую базу $target"
    restore_db_tool dropdb --if-exists --maintenance-db=postgres \
        -U "$AVELREN_RESTORE_ADMIN_DB_USER" "$target"
    restore_db_tool createdb --maintenance-db=postgres \
        -U "$AVELREN_RESTORE_ADMIN_DB_USER" "$target"
    restore_psql -d "$target" -q -c "CREATE EXTENSION IF NOT EXISTS timescaledb;"

    restore_log "timescaledb_pre_restore"
    restore_psql -d "$target" -q -c "SELECT timescaledb_pre_restore();"
    AVELREN_RESTORE_POST_PENDING=true

    restore_log "відновлення даних"
    gunzip -c "$dump" | restore_psql -d "$target" -q -v ON_ERROR_STOP=1

    restore_log "timescaledb_post_restore"
    set +e
    restore_psql -d "$target" -q -c "SELECT timescaledb_post_restore();"
    local post_status=$?
    set -e
    AVELREN_RESTORE_POST_PENDING=false
    if [ "$post_status" -ne 0 ]; then
        restore_log "ПОМИЛКА: timescaledb_post_restore failed (exit=$post_status)"
        exit "$post_status"
    fi

    restore_log "перевірка"
    restore_psql -d "$target" -c "
SELECT (SELECT count(*) FROM observations) AS observations,
       (SELECT count(*) FROM checkpoints) AS checkpoints,
       (SELECT count(*) FROM timescaledb_information.hypertables) AS hypertables,
       (SELECT count(*) FROM timescaledb_information.continuous_aggregates) AS aggregates;"
    restore_log "готово: база $target"
}
