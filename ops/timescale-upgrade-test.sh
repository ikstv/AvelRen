#!/usr/bin/env bash
# Лише синтетична репетиція; не приймає production DSN, project або volume.
set -euo pipefail
[ "$#" -eq 0 ] || { echo 'Arguments are forbidden' >&2; exit 2; }
ROOT=$(cd "$(dirname "$0")/.." && pwd)
WORK=$(mktemp -d)
PROJECT="avelren-upgrade-test-${RANDOM}-${RANDOM}"
readonly ROOT WORK PROJECT
export AVELREN_UPGRADE_ROOT=$ROOT
COMPOSE_FILE="$ROOT/ops/compose.timescale-upgrade-test.yml"
ENV_FILE="$WORK/empty.env"
touch "$ENV_FILE"
PROJECT_DIR=$WORK
if command -v cygpath >/dev/null 2>&1; then
    AVELREN_UPGRADE_ROOT=$(cygpath -w "$ROOT")
    COMPOSE_FILE=$(cygpath -w "$COMPOSE_FILE")
    ENV_FILE=$(cygpath -w "$ENV_FILE")
    PROJECT_DIR=$(cygpath -w "$WORK")
fi
export MSYS_NO_PATHCONV=1
readonly OLD_IMAGE='timescale/timescaledb:2.17.2-pg16@sha256:4e459e217f00cbb09920c34d245501e63427e6767a495de57ce76823ff280f12'
readonly NEW_IMAGE='timescale/timescaledb:2.30.1-pg16@sha256:f495f2bc25ca7596ca8e1606c6241ca250ccc56a0c082b9f2ec0d290e0126cd9'
export AVELREN_UPGRADE_IMAGE=$OLD_IMAGE
BUILT=false
compose() {
    docker compose --project-directory "$PROJECT_DIR" --env-file "$ENV_FILE" \
        -p "$PROJECT" -f "$COMPOSE_FILE" "$@"
}
cleanup() {
    local status=$?
    trap - EXIT
    if [ "$status" -ne 0 ]; then compose logs --tail 60 test-db || true; fi
    compose down --volumes --remove-orphans || status=1
    if [ "$BUILT" = true ]; then docker image rm "$PROJECT-test:latest" >/dev/null || status=1; fi
    rm -f -- "$WORK/empty.env" "$WORK/before.sql.gz" "$WORK/after.sql.gz"
    rmdir -- "$WORK" || status=1
    exit "$status"
}
trap cleanup EXIT
sql() { compose exec -T test-db psql -X -U avelren_admin -d "${1:?database}" -v ON_ERROR_STOP=1 -At -c "${2:?query}"; }
fingerprint() {
    # Новий additive status не змінює fingerprint історичних п'яти полів.
    sql "$1" "SELECT count(*) || ':' || md5(string_agg(row_to_json(o)::text, ',' ORDER BY time, checkpoint_id)) FROM (SELECT time,checkpoint_id,wait_time_seconds,vehicles_in_queue,is_paused FROM observations) o;"
    sql "$1" "SELECT count(*) || ':' || md5(string_agg(row_to_json(o)::text, ',' ORDER BY bucket, checkpoint_id)) FROM observations_hourly o;"
    sql "$1" "SELECT count(*) FROM timescaledb_information.chunks WHERE hypertable_name='observations' AND is_compressed;"
}
legacy_journal() {
    sql "$1" "SELECT md5(string_agg(row_to_json(m)::text, ',' ORDER BY version)) FROM (SELECT version,sha256,applied_at FROM schema_migrations WHERE version < '015') m;"
}
assert_restored_contract() {
    local actual actual_journal statuses
    actual=$(fingerprint restore_test)
    actual_journal=$(legacy_journal restore_test)
    statuses=$(sql restore_test "SELECT count(*) FROM observations WHERE wait_time_status='legacy_unknown'")
    printf 'Restore fingerprint expected:\n%s\nactual:\n%s\n' "$before" "$actual"
    printf 'Restore legacy journal expected=%s actual=%s; legacy rows=%s\n' "$journal_before" "$actual_journal" "$statuses"
    [ "$actual" = "$before" ]
    [ "$actual_journal" = "$journal_before" ]
    [ "$statuses" = 50 ]
}
restore_dump() {
    AVELREN_COMPOSE_PROJECT_DIR="$PROJECT_DIR" AVELREN_COMPOSE_ENV_FILE="$ENV_FILE" \
    AVELREN_ADMIN_PASSWORD=ci-only bash -c \
      'set -euo pipefail; source "$1"; avelren_restore_engine "$2" restore_test "$3" "$4" "$5" test-db' \
      bash "$ROOT/ops/restore-engine.lib.sh" "$1" "$ROOT" "$COMPOSE_FILE" "$PROJECT"
}
docker pull "$OLD_IMAGE"
docker pull "$NEW_IMAGE"
compose build test
BUILT=true
compose up -d --wait test-db
compose exec -T \
    -e AVELREN_TEST_DB=1 -e AVELREN_DB_NAME=avelren_database_test \
    -e AVELREN_ADMIN_DSN=postgresql://avelren_admin:ci-only@127.0.0.1:5432/postgres \
    -e AVELREN_ADMIN_PASSWORD=ci-only -e AVELREN_MIGRATOR_PASSWORD=ci-only \
    -e AVELREN_BACKUP_PASSWORD=ci-only -e AVELREN_COLLECTOR_PASSWORD=ci-only \
    -e AVELREN_NOTIFIER_PASSWORD=ci-only -e AVELREN_WATCHDOG_PASSWORD=ci-only \
    -e AVELREN_API_PASSWORD=ci-only \
    test-db bash /workspace/ops/postgres-bootstrap.sh fresh
# 015 потребує нової extension. Стару історію починаємо з явного prefix,
# не послаблюючи migrate/schema_verify і не редагуючи файли міграцій.
compose run --rm --no-deps -T test sh -eu -c '
    prefix=$(mktemp -d)
    trap '\''rm -f "$prefix"/*.sql; rmdir "$prefix"'\'' EXIT
    for version in $(seq -w 1 14); do
        cp db/migrations/0${version}_*.sql "$prefix/"
    done
    [ "$(find "$prefix" -name "*.sql" | wc -l)" -eq 14 ]
    python -m avelren.migrate "$prefix"
'
[ "$(sql avelren_database_test "SELECT extversion FROM pg_extension WHERE extname='timescaledb'")" = 2.17.2 ]
[ "$(sql avelren_database_test 'SELECT count(*) FROM schema_migrations')" = 14 ]
journal_before=$(legacy_journal avelren_database_test)
sql avelren_database_test "SELECT alter_job(job_id, scheduled => false) FROM timescaledb_information.jobs WHERE proc_name IN ('policy_compression','policy_refresh_continuous_aggregate');"
sql avelren_database_test "INSERT INTO checkpoints(id,title,for_vehicle_type) VALUES(987654320,'upgrade-synthetic',1);
INSERT INTO observations(time,checkpoint_id,wait_time_seconds,vehicles_in_queue,is_paused)
SELECT t,987654320,60,2,false FROM generate_series('2020-01-01'::timestamptz,'2020-01-03'::timestamptz,interval '1 hour') t;
INSERT INTO observations VALUES(now(),987654320,120,3,false);"
sql avelren_database_test "CALL refresh_continuous_aggregate('observations_hourly','2020-01-01'::timestamptz,'2020-01-04'::timestamptz);"
sql avelren_database_test "SELECT compress_chunk(c) FROM show_chunks('observations',older_than=>'2021-01-01'::timestamptz) c;"
[ "$(sql avelren_database_test 'SELECT count(*) FROM observations')" = 50 ]
[ "$(sql avelren_database_test 'SELECT count(*) FROM observations_hourly')" = 49 ]
[ "$(sql avelren_database_test "SELECT count(*) FROM timescaledb_information.chunks WHERE hypertable_name='observations' AND is_compressed")" -gt 0 ]
before=$(fingerprint avelren_database_test)
compose exec -T -e PGPASSWORD=ci-only test-db pg_dump -h 127.0.0.1 -U avelren_backup \
    -d avelren_database_test --no-owner | gzip >"$WORK/before.sql.gz"
# Спочатку доводимо відновлення старої копії на старій версії, а не downgrade каталогу.
restore_dump "$WORK/before.sql.gz"
[ "$(fingerprint restore_test)" = "$before" ]
[ "$(legacy_journal restore_test)" = "$journal_before" ]
echo 'PASS: old-version compressed backup/restore'
# Обидві БД залишаються в тому самому одноразовому volume.
compose stop test-db
export AVELREN_UPGRADE_IMAGE=$NEW_IMAGE
compose up -d --wait test-db
for database in avelren_database_test restore_test postgres template1; do
    # ALTER EXTENSION має бути першим зверненням до extension у новій сесії.
    sql "$database" "ALTER EXTENSION timescaledb UPDATE TO '2.30.1';"
    [ "$(sql "$database" "SELECT extversion FROM pg_extension WHERE extname='timescaledb'")" = 2.30.1 ]
done
[ "$(fingerprint avelren_database_test)" = "$before" ]
[ "$(fingerprint restore_test)" = "$before" ]
echo 'PASS: in-place upgrade preserves raw/aggregate/compressed data'
# Тільки після успішного upgrade на обох БД застосовуємо нову схему.
for database in avelren_database_test restore_test; do
    [ "$(sql "$database" "SELECT extversion FROM pg_extension WHERE extname='timescaledb'")" = 2.30.1 ]
    compose run --rm --no-deps -T \
        -e DATABASE_URL="postgresql://avelren_migrator:ci-only@test-db:5432/$database" \
        test python -m avelren.migrate db/migrations
    [ "$(sql "$database" 'SELECT count(*) FROM schema_migrations')" = 15 ]
    [ "$(legacy_journal "$database")" = "$journal_before" ]
    [ "$(fingerprint "$database")" = "$before" ]
    [ "$(sql "$database" "SELECT count(*) FROM observations WHERE wait_time_status='legacy_unknown'")" = 50 ]
done
echo 'PASS: schema 015 after extension upgrade preserves legacy data/journal/compression'
# Порожні тестові БД успадковують template1: не допустити хибного green на 2.17.2.
sql postgres 'CREATE DATABASE avelren_version_probe_test;'
[ "$(sql avelren_version_probe_test "SELECT extversion FROM pg_extension WHERE extname='timescaledb'")" = 2.30.1 ]
sql postgres 'DROP DATABASE avelren_version_probe_test;'
# Новий dump відновлюється на тій самій новій версії, не змішуючи каталоги extension.
compose exec -T -e PGPASSWORD=ci-only test-db pg_dump -h 127.0.0.1 -U avelren_backup \
    -d avelren_database_test --no-owner | gzip >"$WORK/after.sql.gz"
restore_dump "$WORK/after.sql.gz"
assert_restored_contract
for database in avelren_database_test restore_test; do
    compose run --rm --no-deps -T \
        -e DATABASE_URL="postgresql://avelren_migrator:ci-only@test-db:5432/$database" \
        test python -m avelren.schema_verify db/migrations
    count=$(compose exec -T -e PGPASSWORD=ci-only test-db psql -X -h 127.0.0.1 \
        -U avelren_api -d "$database" -v ON_ERROR_STOP=1 -At -c 'SELECT count(*) FROM observations;')
    [ "$count" = 50 ]
    # Перевіряємо життєвий цикл саме перенесених об'єктів, не лише нових pytest-БД.
    compose exec -T -e PGPASSWORD=ci-only test-db psql -X -h 127.0.0.1 \
        -U avelren_collector -d "$database" -v ON_ERROR_STOP=1 -q \
        -c "INSERT INTO observations VALUES('2020-01-20'::timestamptz,987654320,180,4,false);"
    sql "$database" "CALL refresh_continuous_aggregate('observations_hourly','2020-01-01'::timestamptz,'2020-01-21'::timestamptz);"
    sql "$database" "SELECT compress_chunk(c,if_not_compressed=>true) FROM show_chunks('observations',older_than=>'2021-01-01'::timestamptz) c;"
    [ "$(sql "$database" 'SELECT count(*) FROM observations')" = 51 ]
    [ "$(sql "$database" 'SELECT count(*) FROM observations_hourly')" = 50 ]
    [ "$(sql "$database" "SELECT wait_time_seconds FROM observations WHERE time='2020-01-20'::timestamptz AND checkpoint_id=987654320")" = 180 ]
done
echo 'PASS: new-version compressed backup/restore, schema/API read, collector write/refresh/compression'
compose run --rm --no-deps -T test python -m pytest -c services/backend/pytest.ini \
    services/backend/tests/database -q -p no:cacheprovider
echo 'PASS: upgraded image database/API/watchdog contracts'
