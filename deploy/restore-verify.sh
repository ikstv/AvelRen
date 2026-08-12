#!/usr/bin/env bash
set -euo pipefail

STACK_DIR=${AVELREN_STACK_DIR:-/opt/avelren}
COMPOSE_FILE=${AVELREN_COMPOSE_FILE:-}
COMPOSE_PROJECT=${AVELREN_COMPOSE_PROJECT:-}
SCHEMA_SERVICE=${AVELREN_VERIFY_SCHEMA_SERVICE:-migrate}
API_SERVICE=${AVELREN_VERIFY_API_SERVICE:-api}
MIGRATIONS_DIR=${AVELREN_VERIFY_MIGRATIONS_DIR:-/migrations}
TARGET=${1:-restore_test}
PRODUCTION_TARGET=avelren
PRODUCTION_VERIFY_CONTEXT=AVELREN-INTERNAL-PRODUCTION-VERIFY
MIGRATOR_DATABASE_URL=${AVELREN_VERIFY_MIGRATOR_DSN:-}
API_DATABASE_URL=${AVELREN_VERIFY_API_DSN:-}

compose() {
    local args=(docker compose)
    [ -z "$COMPOSE_FILE" ] || args+=(-f "$COMPOSE_FILE")
    [ -z "$COMPOSE_PROJECT" ] || args+=(-p "$COMPOSE_PROJECT")
    "${args[@]}" "$@"
}

if [ "$TARGET" = "$PRODUCTION_TARGET" ] && \
   [ "${AVELREN_PRODUCTION_VERIFY_CONTEXT:-}" != "$PRODUCTION_VERIFY_CONTEXT" ]; then
    echo "REFUSED: production verification requires the internal orchestrator context" >&2
    exit 2
fi
if [ "$TARGET" != restore_test ] && [ "$TARGET" != "$PRODUCTION_TARGET" ]; then
    echo "REFUSED: unsupported verification target: $TARGET" >&2
    exit 2
fi

[ -n "$MIGRATOR_DATABASE_URL" ] || {
    echo "migrator verification DSN is required" >&2
    exit 2
}
[ -n "$API_DATABASE_URL" ] || {
    echo "API verification DSN is required" >&2
    exit 2
}

cd "$STACK_DIR"
run_in_app() {
    local service=$1 database_url=$2 expected_role=$3
    shift 3
    local args=(
        run --rm -T
        -e "POSTGRES_DB=$TARGET"
        -e "AVELREN_RESTORE_VERIFY_TARGET=$TARGET"
        -e "AVELREN_RESTORE_VERIFY_ROLE=$expected_role"
        -e DATABASE_URL
    )
    if [ "$TARGET" = "$PRODUCTION_TARGET" ]; then
        args+=(
            -e "AVELREN_PRODUCTION_VERIFY_CONTEXT=$PRODUCTION_VERIFY_CONTEXT"
            -e "AVELREN_RESTORE_VERIFY_TARGET=$TARGET"
        )
    fi
    DATABASE_URL="$database_url" compose "${args[@]}" "$service" "$@"
}

echo ">>> schema verification against $TARGET"
run_in_app "$SCHEMA_SERVICE" "$MIGRATOR_DATABASE_URL" avelren_migrator \
    python -m avelren.schema_verify "$MIGRATIONS_DIR"

if [ "$TARGET" = "$PRODUCTION_TARGET" ]; then
    echo ">>> read-only production API smoke against $TARGET"
    run_in_app "$API_SERVICE" "$API_DATABASE_URL" avelren_api \
        python -m avelren.restore_readonly_smoke
else
    echo ">>> disposable API smoke against $TARGET"
    run_in_app "$API_SERVICE" "$API_DATABASE_URL" avelren_api \
        python -m avelren.restore_smoke
fi

echo "restore-verify OK: $TARGET"
