#!/usr/bin/env bash
set -euo pipefail

STACK_DIR=/opt/avelren
TARGET=${1:-restore_test}

if [ "$TARGET" = "avelren" ]; then
    echo "ВІДМОВА: verify проти бойової бази avelren заборонено (A-07)." >&2
    exit 2
fi

cd "$STACK_DIR"
base_dsn=$(grep -E '^DATABASE_URL=' .env | head -1 | cut -d= -f2-)
target_dsn="${base_dsn%/*}/$TARGET"

run_in_app() {
    if [ -n "$base_dsn" ]; then
        sudo docker compose run --rm -T -e "DATABASE_URL=$target_dsn" migrate "$@"
    else
        sudo docker compose run --rm -T -e "POSTGRES_DB=$TARGET" migrate "$@"
    fi
}

echo ">>> schema_verify проти $TARGET"
run_in_app python -m avelren.schema_verify /migrations

echo ">>> restore_smoke проти $TARGET"
run_in_app python -m avelren.restore_smoke

echo "restore-verify OK: $TARGET"
