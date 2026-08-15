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
# The production Compose project must never host disposable verification. On the
# prod host the project defaults to the working-directory name (`avelren`); make
# it overridable so the guard can be exercised in tests.
PRODUCTION_COMPOSE_PROJECT=${AVELREN_PRODUCTION_COMPOSE_PROJECT:-avelren}

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

# Production-project guard for the disposable path. Runs before any docker
# compose command. A disposable verification MUST declare an explicit,
# non-production Compose project; an empty project resolves to the working
# directory name — the production project on the prod host — which is exactly
# how the 2026-08-14 incident recreated the live db. (The production-target
# path below is separately gated by the internal orchestrator context and runs
# against the already-running production db with --no-deps.)
if [ "$TARGET" != "$PRODUCTION_TARGET" ]; then
    [ -n "$COMPOSE_PROJECT" ] || {
        echo "REFUSED: disposable restore verification requires an explicit non-production Compose project (set AVELREN_COMPOSE_PROJECT)" >&2
        exit 2
    }
    [ "$COMPOSE_PROJECT" != "$PRODUCTION_COMPOSE_PROJECT" ] || {
        echo "REFUSED: restore verification must not run in the production Compose project ($PRODUCTION_COMPOSE_PROJECT)" >&2
        exit 2
    }
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
        run --rm --no-deps -T
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
