#!/usr/bin/env bash
set -euo pipefail

STACK_DIR=${AVELREN_STACK_DIR:-/opt/avelren}
COMPOSE_FILE=${AVELREN_COMPOSE_FILE:-}
COMPOSE_PROJECT=${AVELREN_COMPOSE_PROJECT:-}
APP_SERVICE=${AVELREN_VERIFY_APP_SERVICE:-migrate}
MIGRATIONS_DIR=${AVELREN_VERIFY_MIGRATIONS_DIR:-/migrations}
TARGET=${1:-restore_test}
PRODUCTION_TARGET=avelren
PRODUCTION_VERIFY_CONTEXT=AVELREN-INTERNAL-PRODUCTION-VERIFY
ADMIN_DB_USER=${AVELREN_ADMIN_DB_USER:-avelren_admin}
VERIFY_DATABASE_URL=${AVELREN_VERIFY_DATABASE_URL:-}

compose() {
    local args=(docker compose)
    [ -z "$COMPOSE_FILE" ] || args+=(-f "$COMPOSE_FILE")
    [ -z "$COMPOSE_PROJECT" ] || args+=(-p "$COMPOSE_PROJECT")
    "${args[@]}" "$@"
}

if [ "$TARGET" = "$PRODUCTION_TARGET" ] && \
   [ "${AVELREN_PRODUCTION_VERIFY_CONTEXT:-}" != "$PRODUCTION_VERIFY_CONTEXT" ]; then
    echo "ВІДМОВА: production verification дозволена лише internal orchestrator context" >&2
    exit 2
fi
if [ "$TARGET" != restore_test ] && [ "$TARGET" != "$PRODUCTION_TARGET" ]; then
    echo "ВІДМОВА: unsupported verification target: $TARGET" >&2
    exit 2
fi

[ "$ADMIN_DB_USER" = avelren_admin ] || {
    echo "verification database role must be avelren_admin" >&2
    exit 2
}
[ -n "$VERIFY_DATABASE_URL" ] || {
    echo "admin verification DSN is required" >&2
    exit 2
}

cd "$STACK_DIR"
run_in_app() {
    shift
    local args=(run --rm -T -e "POSTGRES_DB=$TARGET" -e DATABASE_URL)
    if [ "$TARGET" = "$PRODUCTION_TARGET" ]; then
        args+=(
            -e "AVELREN_PRODUCTION_VERIFY_CONTEXT=$PRODUCTION_VERIFY_CONTEXT"
            -e "AVELREN_RESTORE_VERIFY_TARGET=$TARGET"
        )
    fi
    DATABASE_URL="$VERIFY_DATABASE_URL" compose "${args[@]}" "$APP_SERVICE" "$@"
}

echo ">>> schema_verify проти $TARGET"
run_in_app schema python -m avelren.schema_verify "$MIGRATIONS_DIR"

if [ "$TARGET" = "$PRODUCTION_TARGET" ]; then
    echo ">>> read-only production smoke проти $TARGET"
    run_in_app smoke python -m avelren.restore_readonly_smoke
else
    echo ">>> disposable restore smoke проти $TARGET"
    run_in_app smoke python -m avelren.restore_smoke
fi

echo "restore-verify OK: $TARGET"
