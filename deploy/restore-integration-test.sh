#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
COMPOSE_FILE="$ROOT/docker-compose.backend-test.yml"
PROJECT=avelren_restore_integration
WORK=$(mktemp -d)
trap 'docker compose -p "$PROJECT" -f "$COMPOSE_FILE" down --volumes --remove-orphans >/dev/null 2>&1 || true; rm -rf "$WORK"' EXIT

compose() {
    docker compose -p "$PROJECT" -f "$COMPOSE_FILE" "$@"
}

SOURCE_DB=avelren_ci
TARGET_DB=restore_test
MARKER=restore-integration-marker-v1
DUMP="$WORK/source.sql.gz"

compose up -d test-db
compose run --rm -T test python -m avelren.migrate db/migrations
compose exec -T test-db psql -U avelren -d "$SOURCE_DB" -q \
    -c 'CREATE TABLE restore_integration_marker (value text PRIMARY KEY);' \
    -c "INSERT INTO restore_integration_marker (value) VALUES ('$MARKER');"
compose exec -T test-db pg_dump -U avelren -d "$SOURCE_DB" --no-owner | gzip -9 > "$DUMP"

AVELREN_STACK_DIR="$ROOT" \
AVELREN_COMPOSE_FILE="$COMPOSE_FILE" \
AVELREN_COMPOSE_PROJECT="$PROJECT" \
AVELREN_DB_SERVICE=test-db \
bash "$ROOT/deploy/restore.sh" "$DUMP" --target "$TARGET_DB"

restored=$(compose exec -T test-db psql -U avelren -d "$TARGET_DB" -At \
    -c "SELECT value FROM restore_integration_marker WHERE value = '$MARKER';")
[ "$restored" = "$MARKER" ] || {
    echo "restore integration failed: deterministic marker missing" >&2
    exit 1
}
compose run --rm -T -e "DATABASE_URL=postgresql://avelren:ci-only@test-db:5432/$TARGET_DB" \
    test python -m avelren.schema_verify db/migrations

echo "restore integration passed: target=$TARGET_DB marker=$MARKER schema=verified"

# Failure after a successful pre_restore must still attempt post_restore and
# preserve a non-zero primary outcome.
bad_dump="$WORK/fails-after-pre.sql.gz"
{
    printf 'THIS IS NOT VALID SQL;\n'
    head -c 20000 /dev/urandom | base64
} | gzip -c >"$bad_dump"
failure_log="$WORK/failure.log"
if AVELREN_STACK_DIR="$ROOT" \
   AVELREN_COMPOSE_FILE="$COMPOSE_FILE" \
   AVELREN_COMPOSE_PROJECT="$PROJECT" \
   AVELREN_DB_SERVICE=test-db \
   bash "$ROOT/deploy/restore.sh" "$bad_dump" --target "$TARGET_DB" \
       >"$failure_log" 2>&1; then
    echo "restore failure after pre_restore was expected" >&2
    exit 1
fi
cat "$failure_log"
grep -q 'primary restore failure' "$failure_log"
grep -q 'timescaledb_post_restore cleanup succeeded' "$failure_log"
echo "restore failure cleanup passed: post_restore attempted, primary failure preserved"
