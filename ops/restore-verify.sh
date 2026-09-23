#!/usr/bin/env bash
set -euo pipefail

STACK_DIR=${AVELREN_STACK_DIR:-/opt/avelren}
COMPOSE_FILE=${AVELREN_COMPOSE_FILE:-}
COMPOSE_PROJECT=${AVELREN_COMPOSE_PROJECT:-}
COMPOSE_PROJECT_DIR=${AVELREN_COMPOSE_PROJECT_DIR:-}
COMPOSE_ENV_FILE=${AVELREN_COMPOSE_ENV_FILE:-}
SCHEMA_SERVICE=${AVELREN_VERIFY_SCHEMA_SERVICE:-migrate}
API_SERVICE=${AVELREN_VERIFY_API_SERVICE:-api}
DB_SERVICE=${AVELREN_RESTORE_VERIFY_DB_SERVICE:-db}
MIGRATIONS_DIR=${AVELREN_VERIFY_MIGRATIONS_DIR:-/migrations}
TARGET=${1:-restore_test}
ENV_GUARD=${AVELREN_COMPOSE_ENV_GUARD:-}
MIGRATOR_DATABASE_URL=${AVELREN_VERIFY_MIGRATOR_DSN:-}
API_DATABASE_URL=${AVELREN_VERIFY_API_DSN:-}

# Incident 2026-08-14: running this script for a disposable target from the
# production Compose project recreated the live `avelren-db-1` container.
# `docker compose run <service>` reconciles the service's depends_on targets, and
# a production `db` whose on-disk compose config had drifted (a git uplift added
# resource limits) was RECREATED to apply the new config — taking the live
# database down. Two structural defenses prevent a recurrence:
#   1. disposable verification refuses unless an explicit, non-production Compose
#      project is set (an empty project would resolve to the production one); and
#   2. every `docker compose run` below uses --no-deps, so `db` is never
#      started or reconciled by the verification containers.
compose() {
    local args=(docker compose)
    [ -z "$COMPOSE_PROJECT_DIR" ] || args+=(--project-directory "$COMPOSE_PROJECT_DIR")
    [ -z "$COMPOSE_ENV_FILE" ] || args+=(--env-file "$COMPOSE_ENV_FILE")
    [ -z "$COMPOSE_FILE" ] || args+=(-f "$COMPOSE_FILE")
    [ -z "$COMPOSE_PROJECT" ] || args+=(-p "$COMPOSE_PROJECT")
    "${args[@]}" "$@"
}

if [ "$TARGET" != restore_test ]; then
    echo "REFUSED: verification supports only the isolated restore_test database" >&2
    exit 2
fi
[ -n "$COMPOSE_FILE" ] && [ -n "$COMPOSE_PROJECT" ] && \
    [ -n "$COMPOSE_PROJECT_DIR" ] && [ -n "$COMPOSE_ENV_FILE" ] && \
    [ "$COMPOSE_PROJECT" != avelren ] && [ "$ENV_GUARD" = isolated ] || {
    echo "REFUSED: restore verification requires an explicit isolated Compose file, project, and guard" >&2
    exit 2
}

[ -n "$MIGRATOR_DATABASE_URL" ] || {
    echo "migrator verification DSN is required" >&2
    exit 2
}
[ -n "$API_DATABASE_URL" ] || {
    echo "API verification DSN is required" >&2
    exit 2
}

cd "$STACK_DIR"
compose exec -T "$DB_SERVICE" sh -c '[ "${AVELREN_COMPOSE_ENV_GUARD:-}" = isolated ]' || {
    echo "REFUSED: database container is missing its isolated restore guard" >&2
    exit 2
}
run_in_app() {
    local service=$1 database_url=$2 expected_role=$3
    shift 3
    local args=(
        run --rm --no-deps -T
        -e "POSTGRES_DB=$TARGET"
        -e "AVELREN_RESTORE_VERIFY_TARGET=$TARGET"
        -e "AVELREN_RESTORE_VERIFY_ROLE=$expected_role"
        -e DATABASE_URL
    )
    DATABASE_URL="$database_url" compose "${args[@]}" "$service" "$@"
}

echo ">>> schema verification against $TARGET"
run_in_app "$SCHEMA_SERVICE" "$MIGRATOR_DATABASE_URL" avelren_migrator \
    python -m avelren.schema_verify "$MIGRATIONS_DIR"

echo ">>> disposable API smoke against $TARGET"
run_in_app "$API_SERVICE" "$API_DATABASE_URL" avelren_api \
    python -m avelren.restore_smoke

echo "restore-verify OK: $TARGET"
