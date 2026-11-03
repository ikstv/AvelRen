#!/usr/bin/env bash
# Real collector daemon and disposable DB; only HTTP transport is synthetic.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PROJECT="avelren-spool-test-${RANDOM}-${RANDOM}"
ROOT_FOR_COMPOSE=$ROOT
if command -v cygpath >/dev/null 2>&1; then ROOT_FOR_COMPOSE=$(cygpath -w "$ROOT"); fi
readonly ROOT PROJECT ROOT_FOR_COMPOSE
postgres_stopped=0
compose() {
    MSYS_NO_PATHCONV=1 docker compose -p "$PROJECT" -f "$ROOT_FOR_COMPOSE/ops/compose.collector-spool-test.yml" "$@"
}
cleanup() {
    local status=$?
    trap - EXIT
    if [ "$postgres_stopped" -eq 1 ]; then
        compose up -d --wait test-db-process || status=1
        postgres_stopped=0
    fi
    if [ "$status" -ne 0 ]; then compose logs --tail 30 collector-test test-db test-db-process || true; fi
    compose down --volumes --remove-orphans || status=1
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
assert_dns() {
    compose run --rm --no-deps -T collector-test python -c \
        'import socket; socket.gethostbyname("test-db")' </dev/null
}
assert_db_ready() {
    compose exec -T test-db-process pg_isready -h 127.0.0.1 -U avelren_admin -d postgres </dev/null
    compose run --rm --no-deps -T \
        -e DATABASE_URL=postgresql://avelren_admin:ci-only@test-db:5432/postgres?connect_timeout=3 \
        collector-test python -c \
        'import os, psycopg; psycopg.connect(os.environ["DATABASE_URL"]).close()' </dev/null
}
assert_db_down() {
    if compose run --rm --no-deps -T \
        -e DATABASE_URL=postgresql://avelren_collector:ci-only@test-db:5432/avelren_spool_test?connect_timeout=3 \
        collector-test python -c \
        'import os, psycopg; psycopg.connect(os.environ["DATABASE_URL"]).close()' </dev/null; then
        echo 'PostgreSQL unexpectedly accepts connections during outage' >&2
        return 1
    fi
}
driver=/workspace/ops/collector-spool-daemon-test.py
admin_dsn=postgresql://avelren_admin:ci-only@test-db:5432/avelren_spool_test
compose build collector-test test-db
compose up -d --wait test-db-process test-db
assert_dns
assert_db_ready
compose exec -T \
    -e AVELREN_TEST_DB=1 -e AVELREN_DB_NAME=avelren_spool_test \
    -e AVELREN_ADMIN_DSN=postgresql://avelren_admin:ci-only@127.0.0.1:5432/postgres \
    -e AVELREN_ADMIN_PASSWORD=ci-only -e AVELREN_MIGRATOR_PASSWORD=ci-only \
    -e AVELREN_BACKUP_PASSWORD=ci-only -e AVELREN_COLLECTOR_PASSWORD=ci-only \
    -e AVELREN_NOTIFIER_PASSWORD=ci-only -e AVELREN_WATCHDOG_PASSWORD=ci-only \
    -e AVELREN_API_PASSWORD=ci-only \
    test-db-process bash /workspace/ops/postgres-bootstrap.sh fresh </dev/null
compose run --rm --no-deps -T \
    -e DATABASE_URL=postgresql://avelren_migrator:ci-only@test-db:5432/avelren_spool_test \
    collector-test python -m avelren.migrate /workspace/db/migrations </dev/null
compose run --rm --no-deps -T -e "DATABASE_URL=$admin_dsn" collector-test python "$driver" seed </dev/null
# Keep the service DNS record present while making PostgreSQL unavailable.
# Stopping the container removes test-db from Docker DNS; pausing it leaves
# TCP connections hanging. Stop only PostgreSQL inside the live container so
# the outage is a fast connection refusal with stable service discovery.
compose stop test-db-process
postgres_stopped=1
assert_dns
assert_db_down
compose up -d collector-test
# Two cycles require four paced requests: workload/details at t=60/120s,
# then workload/details at t=180/240s; 30s is reserved for scheduling/spool I/O.
compose exec -T collector-test python "$driver" wait-cycles 2 270
compose kill -s SIGKILL collector-test
# Preserve 60s between requests while restarting the disposable process.
compose run --rm --no-deps -T collector-test python "$driver" wait-next </dev/null
compose start collector-test
# Existing 2 cycles plus 3 new cycles: 60s startup, requests/details through t=360s,
# plus 30s for scheduling and spool I/O.
compose exec -T collector-test python "$driver" wait-cycles 5 390
compose exec -T collector-test python -m avelren.collector_control capture-only on
compose kill -s SIGKILL collector-test
compose run --rm --no-deps -T collector-test python "$driver" wait-next </dev/null
compose start collector-test
compose exec -T collector-test python "$driver" wait-requests 6 90
compose exec -T collector-test python "$driver" wait-aged
compose up -d --wait test-db-process
postgres_stopped=0
assert_dns
assert_db_ready
compose exec -T -e "DATABASE_URL=$admin_dsn" collector-test python "$driver" paused
compose exec -T collector-test python "$driver" backup
compose exec -T collector-test python -m avelren.collector_control capture-only off
compose exec -T collector-test python "$driver" wait-empty
compose exec -T collector-test python -m avelren.collector_control capture-only on
compose exec -T -e "DATABASE_URL=$admin_dsn" collector-test python "$driver" verify
printf '%s\n' 'collector daemon outage/restart/capture-only/FIFO/recovery contract: PASS'
