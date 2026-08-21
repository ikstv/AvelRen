#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
readonly ROOT
PROJECT="avelren-backend-${RANDOM}-${RANDOM}"
ENV_FILE=$(mktemp)
COMPOSE_FILE="$ROOT/docker-compose.backend-test.yml"
ENV_FILE_FOR_COMPOSE=$ENV_FILE
COMPOSE_FILE_FOR_COMPOSE=$COMPOSE_FILE
if command -v cygpath >/dev/null 2>&1; then
    ENV_FILE_FOR_COMPOSE=$(cygpath -w "$ENV_FILE")
    COMPOSE_FILE_FOR_COMPOSE=$(cygpath -w "$COMPOSE_FILE")
fi
readonly PROJECT ENV_FILE COMPOSE_FILE ENV_FILE_FOR_COMPOSE COMPOSE_FILE_FOR_COMPOSE

printf '%s\n' 'AVELREN_COMPOSE_ENV_GUARD=isolated' >"$ENV_FILE"

compose() {
    MSYS_NO_PATHCONV=1 docker compose --env-file "$ENV_FILE_FOR_COMPOSE" \
        -p "$PROJECT" -f "$COMPOSE_FILE_FOR_COMPOSE" "$@"
}

cleanup() {
    local status=$?
    trap - EXIT
    compose down --volumes --remove-orphans >/dev/null 2>&1 || true
    rm -f "$ENV_FILE"
    exit "$status"
}
trap cleanup EXIT

readonly BOOTSTRAP_DSN='postgresql://avelren_admin:ci-only@localhost:5432/postgres'

compose up --detach --wait test-db
compose exec -T test-db sh -c '[ "$AVELREN_COMPOSE_ENV_GUARD" = isolated ]'
compose exec -T \
    -e AVELREN_TEST_DB=1 \
    -e AVELREN_DB_NAME=avelren_backend_test \
    -e AVELREN_ADMIN_DSN="$BOOTSTRAP_DSN" \
    -e AVELREN_ADMIN_PASSWORD=ci-only \
    -e AVELREN_MIGRATOR_PASSWORD=ci-only \
    -e AVELREN_BACKUP_PASSWORD=ci-only \
    -e AVELREN_COLLECTOR_PASSWORD=ci-only \
    -e AVELREN_NOTIFIER_PASSWORD=ci-only \
    -e AVELREN_WATCHDOG_PASSWORD=ci-only \
    -e AVELREN_API_PASSWORD=ci-only \
    test-db bash /workspace/deploy/postgres-bootstrap.sh fresh

compose run --rm --no-deps -T test python -c '
import psycopg
from avelren.config import settings

with psycopg.connect(settings.database_dsn) as connection:
    identity = connection.execute(
        "SELECT current_user, rolcreaterole FROM pg_roles WHERE rolname = current_user"
    ).fetchone()
if identity != ("avelren_migrator", False):
    raise SystemExit(f"backend test credential is not least privilege: {identity!r}")
'

compose run --rm --no-deps -T test sh -c \
    'ruff check app/src app/tests && python -m avelren.migrate db/migrations'

# Restore-allowlist contract: a purely static check (no DB needed) that
# reconciles the hardcoded allowlist in `deploy/restore-engine.lib.sh` with the
# schema (schema_verify._TABLES_V + `bigserial` in the migrations). Without this
# step a future migration adding a new table passes CI, and production-restore
# catches the mismatch only AFTER dropdb — during DR. `restore-allowlist-
# contract-test.py` exists in the repo but was not wired into the canonical
# gate — we fix that right here, so a single script covers both the local run
# and CI (deploy scripts should be part of the SLO contracts, not a separate
# checklist in the reviewer's head).
compose run --rm --no-deps -T test python3 deploy/restore-allowlist-contract-test.py

compose run --rm --no-deps -T \
    -e DATABASE_URL=postgresql://avelren_admin:ci-only@test-db:5432/avelren_backend_test \
    test python -m pytest app/tests -q -p no:cacheprovider
