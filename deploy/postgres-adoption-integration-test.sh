#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT=$(cd "$(dirname "$0")/.." && pwd)
readonly ROOT

[ "${AVELREN_ADOPTION_SCENARIO:-}" = before_commit ] || \
    [ "${AVELREN_ADOPTION_SCENARIO:-}" = after_commit ] || \
    [ "${AVELREN_ADOPTION_SCENARIO:-}" = success ] || {
    echo 'adoption integration requires AVELREN_ADOPTION_SCENARIO=before_commit, after_commit, or success' >&2
    exit 2
}
FOCUSED_CASE=${AVELREN_ADOPTION_FOCUSED_CASE:-all}
case "$FOCUSED_CASE" in
    all|success|retirement|startup_stop_failure|terminal|committed_capture|committed_verification|committed_cleanup|signal_term|evidence_parent|publisher_validation|late_gates|gate_atomic|committed_marker|rollback_recapture|rollback_fingerprint|invalid_inverse|incomplete_inverse) ;;
    *) echo 'unknown focused adoption integration case' >&2; exit 2 ;;
esac
RETIRE_LEGACY_TEST=${AVELREN_ADOPTION_RETIRE_LEGACY:-0}
case "$RETIRE_LEGACY_TEST" in 0|1) ;; *) echo 'invalid retirement integration selector' >&2; exit 2 ;; esac

ROOT_FOR_COMPOSE=$ROOT
if command -v cygpath >/dev/null 2>&1; then
    ROOT_FOR_COMPOSE=$(cygpath -w "$ROOT")
fi
readonly ROOT_FOR_COMPOSE

PROJECT="avelren-adoption-${RANDOM}-${RANDOM}"
COMPOSE_FILE_POSIX=$(mktemp)
COMPOSE_PROJECT_DIR_POSIX=$(mktemp -d)
COMPOSE_ENV_FILE_POSIX="$COMPOSE_PROJECT_DIR_POSIX/compose.env"
WORK=$(mktemp -d)
readonly PROJECT COMPOSE_FILE_POSIX COMPOSE_PROJECT_DIR_POSIX COMPOSE_ENV_FILE_POSIX WORK

printf '%s\n' 'AVELREN_COMPOSE_ENV_GUARD=isolated' >"$COMPOSE_ENV_FILE_POSIX"
printf '%s\n' 'AVELREN_COMPOSE_ENV_GUARD=poison' >"$COMPOSE_PROJECT_DIR_POSIX/.env"

COMPOSE_FILE=$COMPOSE_FILE_POSIX
COMPOSE_PROJECT_DIR=$COMPOSE_PROJECT_DIR_POSIX
COMPOSE_ENV_FILE=$COMPOSE_ENV_FILE_POSIX
if command -v cygpath >/dev/null 2>&1; then
    COMPOSE_FILE=$(cygpath -w "$COMPOSE_FILE_POSIX")
    COMPOSE_PROJECT_DIR=$(cygpath -w "$COMPOSE_PROJECT_DIR_POSIX")
    COMPOSE_ENV_FILE=$(cygpath -w "$COMPOSE_ENV_FILE_POSIX")
fi
readonly COMPOSE_FILE COMPOSE_PROJECT_DIR COMPOSE_ENV_FILE

REAL_DOCKER=$(command -v docker)
readonly REAL_DOCKER

real_compose() {
    MSYS_NO_PATHCONV=1 "$REAL_DOCKER" compose \
        --project-directory "$COMPOSE_PROJECT_DIR" --env-file "$COMPOSE_ENV_FILE" \
        -p "$PROJECT" -f "$COMPOSE_FILE" "$@"
}

UNSAFE_LINK_MODE_LOG="$WORK/unsafe-link-mode.log"
: >"$UNSAFE_LINK_MODE_LOG"

make_unsafe_link() {
    local target=$1 link=$2 platform
    rm -f -- "$link" || { echo 'unsafe file-link fixture cleanup failed' >&2; return 1; }
    platform=$(uname -s) || { echo 'unsafe file-link platform detection failed' >&2; return 1; }
    case "$platform" in
        Linux*)
            ln -s "$target" "$link" || { echo 'Linux native symlink fixture creation failed' >&2; return 1; }
            [ -L "$link" ] || { echo 'Linux unsafe-link fixture is not a native symlink' >&2; return 1; }
            printf '%s\t%s\n' "$link" linux-native-symlink >>"$UNSAFE_LINK_MODE_LOG" || return 1
            ;;
        MINGW*|MSYS*|CYGWIN*)
            if MSYS=winsymlinks:nativestrict ln -s "$target" "$link" 2>/dev/null; then
                [ -L "$link" ] || { echo 'Windows native symlink fixture is not a symlink' >&2; return 1; }
                printf '%s\t%s\n' "$link" windows-native-symlink >>"$UNSAFE_LINK_MODE_LOG" || return 1
            else
                ln "$target" "$link" || { echo 'Windows hard-link fixture creation failed' >&2; return 1; }
                [ ! -L "$link" ] && [ "$(stat -c '%h' "$link")" -gt 1 ] || {
                    echo 'Windows unsafe-link fallback is not a hard link' >&2
                    return 1
                }
                printf '%s\t%s\n' "$link" windows-hard-link >>"$UNSAFE_LINK_MODE_LOG" || return 1
            fi
            ;;
        *) echo "unsupported unsafe-link fixture platform: $platform" >&2; return 1 ;;
    esac
}

assert_unsafe_link_platform() {
    local link=$1 mode
    mode=$(awk -F '\t' -v link="$link" '$1 == link { found=$2 } END { print found }' \
        "$UNSAFE_LINK_MODE_LOG") || return 1
    case "$mode" in
        linux-native-symlink|windows-native-symlink)
            [ -L "$link" ] || { echo "$mode fixture is not a symlink" >&2; return 1; }
            ;;
        windows-hard-link)
            [ ! -L "$link" ] && [ "$(stat -c '%h' "$link")" -gt 1 ] || {
                echo 'Windows hard-link fixture lost its safety property' >&2
                return 1
            }
            ;;
        *) echo "unsafe file-link fixture mode was not recorded for $link" >&2; return 1 ;;
    esac
}

make_unsafe_directory_link() {
    local target=$1 link=$2 platform link_windows target_windows
    rm -f -- "$link" || { echo 'unsafe directory-link fixture cleanup failed' >&2; return 1; }
    platform=$(uname -s) || { echo 'unsafe directory-link platform detection failed' >&2; return 1; }
    case "$platform" in
        Linux*)
            ln -s "$target" "$link" || { echo 'Linux directory symlink fixture creation failed' >&2; return 1; }
            [ -L "$link" ] || { echo 'Linux directory fixture is not a native symlink' >&2; return 1; }
            printf '%s\t%s\n' "$link" linux-native-directory-symlink >>"$UNSAFE_LINK_MODE_LOG" || return 1
            ;;
        MINGW*|MSYS*|CYGWIN*)
            if MSYS=winsymlinks:nativestrict ln -s "$target" "$link" 2>/dev/null; then
                [ -L "$link" ] || { echo 'Windows native directory symlink fixture is not a symlink' >&2; return 1; }
                printf '%s\t%s\n' "$link" windows-native-directory-symlink >>"$UNSAFE_LINK_MODE_LOG" || return 1
            else
                link_windows=$(cygpath -w "$link") || return 1
                target_windows=$(cygpath -w "$target") || return 1
                cmd.exe //d //c mklink //J "$link_windows" "$target_windows" >/dev/null || {
                    echo 'Windows junction fixture creation failed' >&2
                    return 1
                }
                [ -L "$link" ] && [ -d "$link" ] || {
                    echo 'Windows junction is not exposed as a no-follow directory link' >&2
                    return 1
                }
                printf '%s\t%s\n' "$link" windows-directory-junction >>"$UNSAFE_LINK_MODE_LOG" || return 1
            fi
            ;;
        *) echo "unsupported directory-link fixture platform: $platform" >&2; return 1 ;;
    esac
}

assert_unsafe_directory_link_platform() {
    local link=$1 mode
    mode=$(awk -F '\t' -v link="$link" '$1 == link { found=$2 } END { print found }' \
        "$UNSAFE_LINK_MODE_LOG") || return 1
    case "$mode" in
        linux-native-directory-symlink|windows-native-directory-symlink|windows-directory-junction)
            [ -L "$link" ] && [ -d "$link" ] || {
                echo "$mode fixture is not a no-follow directory link" >&2
                return 1
            }
            ;;
        *) echo "unsafe directory-link fixture mode was not recorded for $link" >&2; return 1 ;;
    esac
}

cleanup() {
    local status=$?
    trap - EXIT
    real_compose down --volumes --remove-orphans >/dev/null 2>&1 || true
    rm -f "$COMPOSE_FILE_POSIX"
    rm -rf "$COMPOSE_PROJECT_DIR_POSIX" "$WORK"
    exit "$status"
}
trap cleanup EXIT

cat >"$COMPOSE_FILE_POSIX" <<EOF
x-runtime: &runtime
  image: timescale/timescaledb:2.17.2-pg16
  entrypoint: ["/bin/sh", "-c"]
  command: ["trap 'exit 0' TERM INT; while :; do sleep 3600; done"]
  depends_on:
    db:
      condition: service_healthy
services:
  db:
    image: timescale/timescaledb:2.17.2-pg16
    environment:
      POSTGRES_USER: clusteradmin
      POSTGRES_PASSWORD: ci-only
      POSTGRES_DB: postgres
      AVELREN_COMPOSE_ENV_GUARD: \${AVELREN_COMPOSE_ENV_GUARD:?missing disposable Compose env guard}
    volumes:
      - '$ROOT_FOR_COMPOSE:/workspace:ro'
    healthcheck:
      # The image exposes a socket-only temporary server during first-time
      # initialization. TCP readiness proves that entrypoint shutdown is over
      # and the final server is accepting connections.
      test: ["CMD-SHELL", "pg_isready -h 127.0.0.1 -U clusteradmin -d postgres"]
      interval: 2s
      timeout: 2s
      retries: 30
  test:
    build:
      context: '$ROOT_FOR_COMPOSE'
      dockerfile: app/Dockerfile.test
    depends_on:
      db:
        condition: service_healthy
  api:
    <<: *runtime
    environment:
      DATABASE_URL: postgresql://avelren_api:api-ci-only@db:5432/avelren_adoption_test
  collector:
    <<: *runtime
    environment:
      DATABASE_URL: postgresql://avelren_collector:collector-ci-only@db:5432/avelren_adoption_test
  notifier:
    <<: *runtime
    environment:
      DATABASE_URL: postgresql://avelren_notifier:notifier-ci-only@db:5432/avelren_adoption_test
  watchdog:
    <<: *runtime
    environment:
      DATABASE_URL: postgresql://avelren_watchdog:watchdog-ci-only@db:5432/avelren_adoption_test
  caddy:
    <<: *runtime
EOF

readonly TARGET_DB=avelren_adoption_test
readonly ADMIN_PASSWORD=ci-only
readonly ADMIN_DSN="postgresql://avelren_admin:ci-only@localhost:5432/$TARGET_DB"
readonly BOOTSTRAP_DSN='postgresql://avelren_admin:ci-only@localhost:5432/postgres'
readonly ADMIN_TOOL_DSN="postgresql://avelren_admin:ci-only@db:5432/$TARGET_DB"
readonly MIGRATOR_DSN="postgresql://avelren_migrator:migrator-ci-only@db:5432/$TARGET_DB"
readonly BACKUP_DSN="postgresql://avelren_backup:backup-ci-only@db:5432/$TARGET_DB"
readonly COLLECTOR_DSN="postgresql://avelren_collector:collector-ci-only@db:5432/$TARGET_DB"
readonly NOTIFIER_DSN="postgresql://avelren_notifier:notifier-ci-only@db:5432/$TARGET_DB"
readonly WATCHDOG_DSN="postgresql://avelren_watchdog:watchdog-ci-only@db:5432/$TARGET_DB"
readonly API_DSN="postgresql://avelren_api:api-ci-only@db:5432/$TARGET_DB"

real_compose up --detach --wait db
db_tcp_ready=0
for _ in $(seq 1 30); do
    if PGPASSWORD="$ADMIN_PASSWORD" real_compose exec -T -e PGPASSWORD db \
        psql -h 127.0.0.1 -U clusteradmin -d postgres -At -c 'SELECT 1;' >/dev/null 2>&1; then
        db_tcp_ready=1
        break
    fi
    sleep 1
done
[ "$db_tcp_ready" -eq 1 ] || {
    echo 'disposable PostgreSQL did not reach bounded TCP readiness' >&2
    real_compose logs --no-color db >&2 || true
    exit 1
}
PGPASSWORD="$ADMIN_PASSWORD" real_compose exec -T -e PGPASSWORD db \
    psql -U clusteradmin -d postgres -v ON_ERROR_STOP=1 -q \
    -c 'DROP EXTENSION IF EXISTS timescaledb;' \
    -c "CREATE ROLE avelren_admin LOGIN SUPERUSER PASSWORD 'ci-only';"
PGPASSWORD="$ADMIN_PASSWORD" real_compose exec -T -e PGPASSWORD db \
    psql -U clusteradmin -d template1 -v ON_ERROR_STOP=1 -q \
    -c 'DROP EXTENSION IF EXISTS timescaledb;'
AVELREN_ADMIN_DSN="$BOOTSTRAP_DSN" AVELREN_ADMIN_PASSWORD="$ADMIN_PASSWORD" \
AVELREN_MIGRATOR_PASSWORD=migrator-ci-only AVELREN_BACKUP_PASSWORD=backup-ci-only \
AVELREN_COLLECTOR_PASSWORD=collector-ci-only AVELREN_NOTIFIER_PASSWORD=notifier-ci-only \
AVELREN_WATCHDOG_PASSWORD=watchdog-ci-only AVELREN_API_PASSWORD=api-ci-only \
real_compose exec -T \
    -e AVELREN_ADMIN_DSN -e AVELREN_ADMIN_PASSWORD -e AVELREN_MIGRATOR_PASSWORD \
    -e AVELREN_BACKUP_PASSWORD -e AVELREN_COLLECTOR_PASSWORD -e AVELREN_NOTIFIER_PASSWORD \
    -e AVELREN_WATCHDOG_PASSWORD -e AVELREN_API_PASSWORD \
    -e AVELREN_DB_NAME="$TARGET_DB" -e AVELREN_TEST_DB=1 \
    db bash /workspace/deploy/postgres-bootstrap.sh fresh

MIGRATIONS="$WORK/migrations-001-009"
mkdir -p "$MIGRATIONS"
cp "$ROOT"/db/migrations/00[1-9]_*.sql "$MIGRATIONS/"
MIGRATIONS_FOR_COMPOSE=$MIGRATIONS
if command -v cygpath >/dev/null 2>&1; then
    MIGRATIONS_FOR_COMPOSE=$(cygpath -w "$MIGRATIONS")
fi
DATABASE_URL="$MIGRATOR_DSN" real_compose run --rm --no-deps -T \
    -v "$MIGRATIONS_FOR_COMPOSE:/prefix-migrations:ro" -e DATABASE_URL \
    test python -m avelren.migrate /prefix-migrations

# Materialize a real Timescale chunk so provenance and exact-owner checks cannot
# pass against extension metadata alone.
#
# The chunk must exist BEFORE the manifest is captured and no further chunk may
# appear while adoption runs: a chunk materialising mid-run adds catalog rows the
# captured manifest never saw, and the exact inverse-rollback comparison then
# reports a mismatch even though the rollback itself was perfect. Timescale's
# default 7-day chunks are epoch-aligned (1970-01-01 was a Thursday), so a fixed
# fixture date and the runtime `now()` inserts drift into different chunks as the
# calendar moves. 2026-08-13 00:00 UTC is exactly such a boundary (day 20678 =
# 2954*7), which is why every run from that date failed while the day before
# passed on identical code. Pin the interval so the fixture and every runtime
# insert always share one chunk, and seed at `now()` rather than a fixed date.
#
# The interval is deliberately ~100 years rather than production's 7 days: an
# epoch-aligned 36500-day bucket spans roughly 1970-2069, so every timestamp this
# suite can produce lands in one chunk and the next boundary is unreachable
# within the life of the test. Do NOT "restore realism" by lowering it back to 7
# days. Chunk-interval fidelity proves nothing here — this suite verifies
# owner/ACL manifests, not partitioning behaviour — and lowering it re-arms the
# exact failure described above, silently, on a date nobody will predict.
PGPASSWORD="$ADMIN_PASSWORD" real_compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$TARGET_DB" -v ON_ERROR_STOP=1 -q <<'SQL'
SELECT set_chunk_time_interval('public.observations', INTERVAL '36500 days');
INSERT INTO public.checkpoints (id, title, for_vehicle_type)
VALUES (-1, 'Task 6 ownership fixture', 1);
INSERT INTO public.observations
    (time, checkpoint_id, wait_time_seconds, vehicles_in_queue, is_paused)
VALUES (now(), -1, 60, 1, false);
SQL

# Make a production-like pre-adoption database: legacy owns the database,
# schema, Timescale extension, application objects, and Timescale dependants.
PGPASSWORD="$ADMIN_PASSWORD" real_compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d postgres -v ON_ERROR_STOP=1 -q <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'avelren') THEN
        CREATE ROLE avelren LOGIN SUPERUSER PASSWORD 'legacy-ci-only';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'unexpected_acl_role') THEN
        CREATE ROLE unexpected_acl_role NOLOGIN;
    END IF;
END
\$\$;
DROP DATABASE IF EXISTS avelren_residual_test;
CREATE DATABASE avelren_residual_test OWNER clusteradmin;
ALTER DATABASE "$TARGET_DB" OWNER TO avelren;
SQL
PGPASSWORD="$ADMIN_PASSWORD" real_compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$TARGET_DB" -v ON_ERROR_STOP=1 -q <<'SQL'
REASSIGN OWNED BY avelren_admin TO avelren;
REASSIGN OWNED BY avelren_migrator TO avelren;
SQL

BIN="$WORK/bin"
mkdir -p "$BIN"
cat >"$BIN/psql" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
input=$(mktemp)
trap 'rm -f "$input"' EXIT
cat >"$input"
if [ "${ADOPTION_EVIDENCE_FAULT:-}" = rollback_recapture ] &&
    [ -f "$ADOPTION_FAULT_DIR/fail-next-capture" ]; then
    rm -f "$ADOPTION_FAULT_DIR/fail-next-capture"
    echo 'rollback recapture FAIL (injected)' >&2
    exit 93
fi
if grep -Fq 'INVERSE_APPLIED' "$input"; then
    if [ "${ADOPTION_INVERSE_STAGE_TEST:-0}" = 1 ]; then
        grep -Fxq 'stage=committed' "$AVELREN_EVIDENCE_DIR/stage" || {
            echo 'inverse started before committed stage evidence' >&2
            exit 91
        }
        grep -Fxq 'inverse_verified=NOT_RUN' "$AVELREN_EVIDENCE_DIR/stage" || {
            echo 'inverse was claimed verified before exact restoration' >&2
            exit 92
        }
        printf '%s\n' PASS >"$ADOPTION_INVERSE_STAGE_LOG"
    fi
    if [ "${ADOPTION_EVIDENCE_FAULT:-}" = rollback_recapture ]; then
        : >"$ADOPTION_FAULT_DIR/fail-next-capture"
    fi
fi
if grep -Fq "SELECT 'FORWARD_TARGET_VERIFIED';" "$input"; then
    printf '%s\n' committed >>"$ADOPTION_FORWARD_LOG"
fi
MSYS_NO_PATHCONV=1 "$ADOPTION_REAL_DOCKER" compose \
    --project-directory "$ADOPTION_PROJECT_DIR" --env-file "$ADOPTION_ENV_FILE" \
    -p "$ADOPTION_PROJECT" -f "$ADOPTION_COMPOSE_FILE" \
    exec -T -e PGPASSWORD=ci-only db \
    psql -U avelren_admin -d avelren_adoption_test "$@" <"$input"
SH
cat >"$BIN/docker" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$ADOPTION_SERVICE_LOG"
state=$(cat "$ADOPTION_SERVICE_STATE" 2>/dev/null || printf running)
case " $* " in
    *' ps --status running --services '*)
        if [ "$state" = running ]; then
            printf '%s\n' db caddy api collector notifier watchdog
        else
            printf '%s\n' db
        fi
        ;;
    *' stop caddy api collector notifier watchdog '*)
        if [ "$state" = partial ] && [ "${ADOPTION_NEW_RUNTIME_STOP_FAULT:-0}" = 1 ] && \
           [ ! -e "$ADOPTION_FAULT_DIR/startup-stop-fault-consumed" ]; then
            : >"$ADOPTION_FAULT_DIR/startup-stop-fault-consumed"
            echo 'new runtime stop failure injected' >&2
            exit 72
        fi
        printf '%s\n' stopped >"$ADOPTION_SERVICE_STATE"
        ;;
    *' stop '*) printf '%s\n' stopped >"$ADOPTION_SERVICE_STATE" ;;
    *' up '*)
        if grep -Fxq 'stage=cutover_complete' "$AVELREN_EVIDENCE_DIR/stage" 2>/dev/null; then
            if [ "${ADOPTION_NEW_RUNTIME_UP_FAULT:-0}" = 1 ] && \
               [ ! -e "$ADOPTION_FAULT_DIR/startup-up-fault-consumed" ]; then
                : >"$ADOPTION_FAULT_DIR/startup-up-fault-consumed"
                printf '%s\n' partial >"$ADOPTION_SERVICE_STATE"
                echo 'new runtime startup failure injected' >&2
                exit 71
            fi
            cat >"$ADOPTION_FAULT_DIR/expected-success-gates" <<'EOF'
migrate
privilege_contracts
compose_credential_switch
smoke
collector_freshness
environment_isolation
EOF
            cmp -s "$ADOPTION_FAULT_DIR/expected-success-gates" "$ADOPTION_GATE_LOG" || {
                echo 'new runtime start attempted before every success gate passed' >&2
                exit 1
            }
            for result in privilege_contract_result environment_isolation_result smoke_result freshness_result accepted_cutover; do
                grep -Fxq "$result=PASS" "$AVELREN_EVIDENCE_DIR/stage" || {
                    echo "new runtime start attempted before $result" >&2
                    exit 1
                }
            done
            MSYS_NO_PATHCONV=1 "$ADOPTION_REAL_DOCKER" compose \
                --project-directory "$ADOPTION_PROJECT_DIR" --env-file "$ADOPTION_ENV_FILE" \
                -p "$ADOPTION_PROJECT" -f "$ADOPTION_COMPOSE_FILE" \
                up --detach caddy api collector notifier watchdog >/dev/null
        elif ! cmp -s "$AVELREN_EVIDENCE_DIR/original.tsv" \
                    "$AVELREN_EVIDENCE_DIR/after-failure.tsv" ||
             ! cmp -s "$AVELREN_EVIDENCE_DIR/original.sha256" \
                    "$AVELREN_EVIDENCE_DIR/after-failure.sha256" ||
             ! grep -Fxq 'stage=post_commit_rollback' "$AVELREN_EVIDENCE_DIR/stage" ||
             ! grep -Fxq 'inverse_verified=PASS' "$AVELREN_EVIDENCE_DIR/stage"; then
                echo 'restart attempted before exact inverse verification' >&2
                exit 1
        fi
        printf '%s\n' running >"$ADOPTION_SERVICE_STATE"
        ;;
esac
SH
cat >"$BIN/success-gate" <<'SH'
#!/usr/bin/env bash
set -euo pipefail

gate=${1:?success gate is required}
[ "$(cat "$ADOPTION_SERVICE_STATE")" = stopped ] || {
    echo "$gate ran after the new runtime started" >&2
    exit 1
}

compose() {
    MSYS_NO_PATHCONV=1 "$ADOPTION_REAL_DOCKER" compose \
        --project-directory "$ADOPTION_PROJECT_DIR" --env-file "$ADOPTION_ENV_FILE" \
        -p "$ADOPTION_PROJECT" -f "$ADOPTION_COMPOSE_FILE" "$@"
}

case "$gate" in
    migrate)
        DATABASE_URL="$AVELREN_MIGRATOR_DSN" compose run --rm --no-deps -T \
            -e DATABASE_URL test python -m avelren.migrate db/migrations
        DATABASE_URL="$AVELREN_MIGRATOR_DSN" compose run --rm --no-deps -T \
            -e DATABASE_URL test python - <<'PY'
import os
import psycopg

with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as connection:
    role = connection.execute("SELECT current_user").fetchone()[0]
    connection.execute("SELECT count(*) FROM schema_migrations").fetchone()
print(f"schema_verification_role={role}")
PY
        ;;
    privilege_contracts)
        DATABASE_URL="$AVELREN_MIGRATOR_DSN" compose run --rm --no-deps -T \
            -e DATABASE_URL test python - <<'PY'
import os
import psycopg

with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as connection:
    role = connection.execute("SELECT current_user").fetchone()[0]
    connection.execute("DELETE FROM observations WHERE checkpoint_id = -1")
print(f"application_dml_role={role}")
PY
        DATABASE_URL="$AVELREN_API_DSN" \
        ADMIN_DATABASE_URL="$AVELREN_ADMIN_TOOL_DSN" \
        MIGRATOR_DATABASE_URL="$AVELREN_MIGRATOR_DSN" \
        BACKUP_DATABASE_URL="$AVELREN_BACKUP_DSN" \
        COLLECTOR_DATABASE_URL="$AVELREN_COLLECTOR_DSN" \
        NOTIFIER_DATABASE_URL="$AVELREN_NOTIFIER_DSN" \
        WATCHDOG_DATABASE_URL="$AVELREN_WATCHDOG_DSN" \
        API_DATABASE_URL="$AVELREN_API_DSN" \
        compose run --rm --no-deps -T \
            -e DATABASE_URL -e ADMIN_DATABASE_URL -e MIGRATOR_DATABASE_URL \
            -e BACKUP_DATABASE_URL \
            -e COLLECTOR_DATABASE_URL -e NOTIFIER_DATABASE_URL \
            -e WATCHDOG_DATABASE_URL -e API_DATABASE_URL -e AVELREN_TEST_DB=1 \
            test python -m pytest app/tests/test_db_privileges.py -q -p no:cacheprovider
        ;;
    compose_credential_switch)
        compose create caddy api collector notifier watchdog >/dev/null
        ;;
    smoke)
        DATABASE_URL="$AVELREN_API_DSN" compose run --rm --no-deps -T \
            -e DATABASE_URL test python - <<'PY'
import os
import psycopg
from fastapi.testclient import TestClient

from avelren.api import app

with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as connection:
    role = connection.execute("SELECT current_user").fetchone()[0]
with TestClient(app) as client:
    assert client.get("/health").status_code == 200
    assert client.get("/checkpoints").status_code == 200
print(f"application_verification_role={role}")
PY
        ;;
    collector_freshness)
        DATABASE_URL="$AVELREN_COLLECTOR_DSN" compose run --rm --no-deps -T \
            -e DATABASE_URL test python - <<'PY'
import os
import psycopg

with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as connection:
    role = connection.execute("SELECT current_user").fetchone()[0]
    connection.execute(
        "INSERT INTO collector_runs "
        "(time, http_status, duration_ms, body_sha256, rows_written, error) "
        "VALUES (clock_timestamp(), 200, 1, 'adoption-success-freshness', 1, NULL)"
    )
print(f"freshness_write_role={role}")
PY
        DATABASE_URL="$AVELREN_WATCHDOG_DSN" compose run --rm --no-deps -T \
            -e DATABASE_URL test python - <<'PY'
import os
import psycopg

with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as connection:
    role = connection.execute("SELECT current_user").fetchone()[0]
    fresh = connection.execute(
        "SELECT EXISTS ("
        "SELECT 1 FROM collector_runs "
        "WHERE time >= clock_timestamp() - INTERVAL '1 minute' "
        "AND body_sha256 = 'adoption-success-freshness' "
        "AND error IS NULL AND rows_written > 0)"
    ).fetchone()[0]
assert fresh
print(f"freshness_verification_role={role}")
PY
        ;;
    environment_isolation)
        for service in api collector notifier watchdog caddy; do
            container_id=$(compose ps -aq "$service")
            [ -n "$container_id" ] || { echo "$service container was not created" >&2; exit 1; }
            container_environment=$("$ADOPTION_REAL_DOCKER" inspect --format \
                '{{range .Config.Env}}{{println .}}{{end}}' "$container_id")
            for forbidden in "$AVELREN_ADMIN_DSN" "$AVELREN_ADMIN_TOOL_DSN" \
                "$AVELREN_MIGRATOR_DSN" "$AVELREN_BACKUP_DSN" 'legacy-ci-only'; do
                ! grep -Fq "$forbidden" <<<"$container_environment" || {
                    echo "$service contains an operational credential" >&2
                    exit 1
                }
            done
            case "$service" in
                api) expected=$AVELREN_API_DSN ;;
                collector) expected=$AVELREN_COLLECTOR_DSN ;;
                notifier) expected=$AVELREN_NOTIFIER_DSN ;;
                watchdog) expected=$AVELREN_WATCHDOG_DSN ;;
                caddy) expected= ;;
            esac
            if [ -n "$expected" ]; then
                grep -Fxq "DATABASE_URL=$expected" <<<"$container_environment" || {
                    echo "$service lacks its dedicated runtime credential" >&2
                    exit 1
                }
            else
                ! grep -q '^DATABASE_URL=' <<<"$container_environment" || {
                    echo 'caddy unexpectedly contains a database credential' >&2
                    exit 1
                }
            fi
        done
        ;;
    *) echo 'unknown success gate' >&2; exit 2 ;;
esac

printf '%s\n' "$gate" >>"$ADOPTION_GATE_LOG"
SH
cat >"$BIN/retirement-gate" <<'SH'
#!/usr/bin/env bash
set -euo pipefail

gate=${1:?retirement gate is required}
for forbidden_name in AVELREN_ADMIN_DSN AVELREN_ADMIN_TOOL_DSN ADMIN_DATABASE_URL; do
    [ -z "${!forbidden_name:-}" ] || {
        echo "retirement verification inherited $forbidden_name" >&2
        exit 1
    }
done

compose() {
    MSYS_NO_PATHCONV=1 "$ADOPTION_REAL_DOCKER" compose \
        --project-directory "$ADOPTION_PROJECT_DIR" --env-file "$ADOPTION_ENV_FILE" \
        -p "$ADOPTION_PROJECT" -f "$ADOPTION_COMPOSE_FILE" "$@"
}

case "$gate" in
    privilege_contracts)
        DATABASE_URL="$AVELREN_MIGRATOR_DSN" compose run --rm --no-deps -T \
            -e DATABASE_URL test python - <<'PY'
import os
import psycopg

with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as connection:
    assert connection.execute("SELECT current_user").fetchone()[0] == "avelren_migrator"
    connection.execute("SELECT count(*) FROM schema_migrations").fetchone()
PY
        DATABASE_URL="$AVELREN_API_DSN" \
        BACKUP_DATABASE_URL="$AVELREN_BACKUP_DSN" \
        COLLECTOR_DATABASE_URL="$AVELREN_COLLECTOR_DSN" \
        NOTIFIER_DATABASE_URL="$AVELREN_NOTIFIER_DSN" \
        WATCHDOG_DATABASE_URL="$AVELREN_WATCHDOG_DSN" \
        API_DATABASE_URL="$AVELREN_API_DSN" \
        compose run --rm --no-deps -T \
            -e DATABASE_URL -e BACKUP_DATABASE_URL -e COLLECTOR_DATABASE_URL \
            -e NOTIFIER_DATABASE_URL -e WATCHDOG_DATABASE_URL -e API_DATABASE_URL \
            -e AVELREN_TEST_DB=1 \
            test python -m pytest app/tests/test_db_privileges.py -q -p no:cacheprovider \
            -k 'test_role_has_no_elevated_capability or test_runtime_role_cannot_escalate_or_change_migration_history or test_role_specific_negative_matrix or test_table_privileges_match_frozen_acl or test_sequence_privileges_match_frozen_acl or test_device_column_privileges_match_frozen_acl or test_column_scoped_updates_match_frozen_acl or test_column_scoped_selects_match_frozen_acl or test_notification_cancel_conflict_target_positive_select_is_allowed'
        ;;
    environment_isolation)
        for service in api collector notifier watchdog caddy; do
            container_id=$(compose ps -aq "$service")
            [ -n "$container_id" ] || { echo "$service container is missing" >&2; exit 1; }
            container_environment=$("$ADOPTION_REAL_DOCKER" inspect --format \
                '{{range .Config.Env}}{{println .}}{{end}}' "$container_id")
            for forbidden in 'postgresql://avelren_admin:' 'postgresql://avelren_migrator:' \
                'postgresql://avelren_backup:' 'postgresql://avelren:' 'legacy-ci-only'; do
                ! grep -Fq "$forbidden" <<<"$container_environment" || {
                    echo "$service contains an operational or legacy credential" >&2
                    exit 1
                }
            done
        done
        ;;
    *) echo 'unknown retirement gate' >&2; exit 2 ;;
esac

printf '%s\n' "$gate" >>"$ADOPTION_RETIREMENT_GATE_LOG"
SH
chmod +x "$BIN/psql" "$BIN/docker" "$BIN/success-gate" "$BIN/retirement-gate"
export AVELREN_PSQL_BIN="$BIN/psql"
export ADOPTION_REAL_DOCKER="$REAL_DOCKER"
export ADOPTION_PROJECT_DIR="$COMPOSE_PROJECT_DIR"
export ADOPTION_ENV_FILE="$COMPOSE_ENV_FILE"
export ADOPTION_PROJECT="$PROJECT"
export ADOPTION_COMPOSE_FILE="$COMPOSE_FILE"

# shellcheck source=deploy/postgres-ownership.lib.sh
source "$ROOT/deploy/postgres-ownership.lib.sh"

PLAN_EVIDENCE="$WORK/plan-evidence"
prepare_evidence_dir "$PLAN_EVIDENCE"
AVELREN_TARGET_DB="$TARGET_DB" capture_manifest "$ADMIN_DSN" "$PLAN_EVIDENCE/original.tsv"
grep -Eq $'^object\trelation\t[^\t]+\tpublic\talerts_pkey\ti\tavelren\tdependency:' \
    "$PLAN_EVIDENCE/original.tsv" || {
    echo 'canonical manifest omitted an application index ownership dependency' >&2
    exit 1
}
grep -Eq $'^object\trelation\t[^\t]+\tpg_toast\t[^\t]+\tt\tavelren\tdependency:' \
    "$PLAN_EVIDENCE/original.tsv" || {
    echo 'canonical manifest omitted an application TOAST ownership dependency' >&2
    exit 1
}
grep -Eq $'^object\ttype\t[^\t]+\tpublic\talerts\tc\tavelren\trelation:' \
    "$PLAN_EVIDENCE/original.tsv" || {
    echo 'canonical manifest omitted an application row-type ownership dependency' >&2
    exit 1
}
grep -Eq $'^object\ttype\t[^\t]+\tpublic\t_alerts\tb\tavelren\ttype:' \
    "$PLAN_EVIDENCE/original.tsv" || {
    echo 'canonical manifest omitted an application array-type ownership dependency' >&2
    exit 1
}
grep -Eq $'^object\trelation\t[^\t]+\t_timescaledb_internal\t[^\t]+\tr\tavelren\ttimescale:[^\t]*chunk_catalog:' \
    "$PLAN_EVIDENCE/original.tsv" || {
    echo 'canonical manifest omitted a catalog-proven TimescaleDB chunk' >&2
    exit 1
}
AVELREN_TARGET_DB="$TARGET_DB" build_forward_plan \
    "$PLAN_EVIDENCE/original.tsv" "$PLAN_EVIDENCE/forward.sql" \
    "$ROOT/db/migrations/010_postgresql_least_privilege.sql"
AVELREN_TARGET_DB="$TARGET_DB" build_inverse_plan \
    "$PLAN_EVIDENCE/original.tsv" "$PLAN_EVIDENCE/inverse.sql"

assert_target_check_rejects() {
    local name=$1 tamper=$2 expected_error=$3 driver output after_manifest
    driver="$WORK/$name.driver.sql"
    output="$WORK/$name.out"
    after_manifest="$WORK/$name.after.tsv"
    {
        printf '%s\n' '\set ON_ERROR_STOP on' 'BEGIN;'
        cat "$PLAN_EVIDENCE/forward.sql"
        cat "$tamper"
        _target_ownership_sql "$PLAN_EVIDENCE/original.tsv"
        printf '%s\n' "SELECT 'TARGET_CHECK_ACCEPTED';" "SELECT 'INVERSE_STARTED';"
        cat "$PLAN_EVIDENCE/inverse.sql"
        printf '%s\n' 'ROLLBACK;'
    } >"$driver"
    if _adoption_psql "$ADMIN_DSN" <"$driver" >"$output" 2>&1; then
        echo "$name target-state drift should fail closed" >&2
        exit 1
    fi
    ! grep -q 'INVERSE_STARTED' "$output" || {
        echo "$name reached inverse progression" >&2
        exit 1
    }
    grep -q "$expected_error" "$output" || {
        echo "$name failed for the wrong reason" >&2
        sed -n '1,120p' "$output" >&2 || true
        exit 1
    }
    AVELREN_TARGET_DB="$TARGET_DB" capture_manifest "$ADMIN_DSN" "$after_manifest"
    cmp "$PLAN_EVIDENCE/original.tsv" "$after_manifest" || {
        echo "$name left ownership or ACL mutation after rejection" >&2
        exit 1
    }
}

assert_target_check_accepts() {
    local name=$1 tamper=$2 driver output after_manifest
    driver="$WORK/$name.driver.sql"
    output="$WORK/$name.out"
    after_manifest="$WORK/$name.after.tsv"
    {
        printf '%s\n' '\set ON_ERROR_STOP on' 'BEGIN;'
        cat "$PLAN_EVIDENCE/forward.sql"
        cat "$tamper"
        _target_ownership_sql "$PLAN_EVIDENCE/original.tsv"
        printf '%s\n' "SELECT 'TARGET_CHECK_ACCEPTED';"
        cat "$PLAN_EVIDENCE/inverse.sql"
        printf '%s\n' 'ROLLBACK;'
    } >"$driver"
    _adoption_psql "$ADMIN_DSN" <"$driver" >"$output" 2>&1 || {
        echo "$name canonical target state should be accepted" >&2
        sed -n '1,160p' "$output" >&2 || true
        exit 1
    }
    grep -q 'TARGET_CHECK_ACCEPTED' "$output" || {
        echo "$name did not execute the target verifier" >&2
        exit 1
    }
    AVELREN_TARGET_DB="$TARGET_DB" capture_manifest "$ADMIN_DSN" "$after_manifest"
    cmp "$PLAN_EVIDENCE/original.tsv" "$after_manifest" || {
        echo "$name left ownership or ACL mutation after rollback" >&2
        exit 1
    }
}

if [ "$FOCUSED_CASE" = all ]; then
cat >"$WORK/acl-unknown-grantee.sql" <<'SQL'
GRANT SELECT ON TABLE public.alerts TO unexpected_acl_role;
SQL
assert_target_check_rejects acl-unknown-grantee "$WORK/acl-unknown-grantee.sql" \
    'target ACL exact-set mismatch'

cat >"$WORK/acl-table-drift.sql" <<'SQL'
GRANT UPDATE ON TABLE public.alerts TO avelren_watchdog;
SQL
assert_target_check_rejects acl-table-drift "$WORK/acl-table-drift.sql" \
    'target ACL exact-set mismatch'

cat >"$WORK/acl-column-drift.sql" <<'SQL'
GRANT SELECT (fcm_token) ON TABLE public.devices TO avelren_collector;
SQL
assert_target_check_rejects acl-column-drift "$WORK/acl-column-drift.sql" \
    'target ACL exact-set mismatch'

cat >"$WORK/acl-grant-option-drift.sql" <<'SQL'
GRANT SELECT ON TABLE public.checkpoints TO avelren_api WITH GRANT OPTION;
SQL
assert_target_check_rejects acl-grant-option-drift "$WORK/acl-grant-option-drift.sql" \
    'target ACL exact-set mismatch'

cat >"$WORK/acl-grantor-drift.sql" <<'SQL'
GRANT USAGE ON SCHEMA public TO unexpected_acl_role;
GRANT SELECT ON TABLE public.alerts TO unexpected_acl_role WITH GRANT OPTION;
SET ROLE unexpected_acl_role;
GRANT SELECT ON TABLE public.alerts TO avelren_notifier;
RESET ROLE;
SQL
assert_target_check_rejects acl-grantor-drift "$WORK/acl-grantor-drift.sql" \
    'target ACL exact-set mismatch'

cat >"$WORK/default-acl-drift.sql" <<'SQL'
ALTER DEFAULT PRIVILEGES FOR ROLE avelren_migrator IN SCHEMA public
    GRANT SELECT ON TABLES TO avelren_watchdog;
SQL
assert_target_check_rejects default-acl-drift "$WORK/default-acl-drift.sql" \
    'target default-privilege'

cat >"$WORK/default-function-owner-missing.sql" <<'SQL'
ALTER DEFAULT PRIVILEGES FOR ROLE avelren_migrator
    REVOKE EXECUTE ON FUNCTIONS FROM avelren_migrator;
SQL
assert_target_check_rejects default-function-owner-missing \
    "$WORK/default-function-owner-missing.sql" \
    'target default-privilege ACL exact-set mismatch'

cat >"$WORK/default-type-owner-missing.sql" <<'SQL'
ALTER DEFAULT PRIVILEGES FOR ROLE avelren_migrator
    REVOKE USAGE ON TYPES FROM avelren_migrator;
SQL
assert_target_check_rejects default-type-owner-missing \
    "$WORK/default-type-owner-missing.sql" \
    'target default-privilege ACL exact-set mismatch'

cat >"$WORK/default-function-schema-dash-substitution.sql" <<'SQL'
CREATE SCHEMA "-" AUTHORIZATION avelren_admin;
ALTER DEFAULT PRIVILEGES FOR ROLE avelren_migrator
    GRANT EXECUTE ON FUNCTIONS TO PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE avelren_migrator IN SCHEMA "-"
    GRANT EXECUTE ON FUNCTIONS TO avelren_migrator;
SQL
assert_target_check_rejects default-function-schema-dash-substitution \
    "$WORK/default-function-schema-dash-substitution.sql" \
    'target default-privilege'

cat >"$WORK/default-type-empty-schema-dash-substitution.sql" <<'SQL'
CREATE SCHEMA "-" AUTHORIZATION avelren_admin;
ALTER DEFAULT PRIVILEGES FOR ROLE avelren_migrator
    REVOKE USAGE ON TYPES FROM avelren_migrator;
ALTER DEFAULT PRIVILEGES FOR ROLE avelren_migrator IN SCHEMA "-"
    GRANT USAGE ON TYPES TO avelren_migrator;
SQL
assert_target_check_rejects default-type-empty-schema-dash-substitution \
    "$WORK/default-type-empty-schema-dash-substitution.sql" \
    'target default-privilege'

cat >"$WORK/default-function-schema-dash-duplicate.sql" <<'SQL'
CREATE SCHEMA "-" AUTHORIZATION avelren_admin;
ALTER DEFAULT PRIVILEGES FOR ROLE avelren_migrator IN SCHEMA "-"
    GRANT EXECUTE ON FUNCTIONS TO avelren_migrator;
SQL
assert_target_check_rejects default-function-schema-dash-duplicate \
    "$WORK/default-function-schema-dash-duplicate.sql" \
    'target default-privilege'

cat >"$WORK/default-function-public.sql" <<'SQL'
ALTER DEFAULT PRIVILEGES FOR ROLE avelren_migrator
    GRANT EXECUTE ON FUNCTIONS TO PUBLIC;
SQL
assert_target_check_rejects default-function-public "$WORK/default-function-public.sql" \
    'target default-privilege'

cat >"$WORK/default-type-public.sql" <<'SQL'
ALTER DEFAULT PRIVILEGES FOR ROLE avelren_migrator
    GRANT USAGE ON TYPES TO PUBLIC;
SQL
assert_target_check_rejects default-type-public "$WORK/default-type-public.sql" \
    'target default-privilege'

cat >"$WORK/default-table-public.sql" <<'SQL'
ALTER DEFAULT PRIVILEGES FOR ROLE avelren_migrator IN SCHEMA public
    GRANT SELECT ON TABLES TO PUBLIC;
SQL
assert_target_check_rejects default-table-public "$WORK/default-table-public.sql" \
    'target default-privilege'

cat >"$WORK/default-sequence-public.sql" <<'SQL'
ALTER DEFAULT PRIVILEGES FOR ROLE avelren_migrator IN SCHEMA public
    GRANT USAGE ON SEQUENCES TO PUBLIC;
SQL
assert_target_check_rejects default-sequence-public "$WORK/default-sequence-public.sql" \
    'target default-privilege'

cat >"$WORK/default-unexpected-grantee.sql" <<'SQL'
ALTER DEFAULT PRIVILEGES FOR ROLE avelren_migrator
    GRANT EXECUTE ON FUNCTIONS TO unexpected_acl_role;
SQL
assert_target_check_rejects default-unexpected-grantee \
    "$WORK/default-unexpected-grantee.sql" 'target default-privilege'

cat >"$WORK/default-unexpected-grant-option.sql" <<'SQL'
ALTER DEFAULT PRIVILEGES FOR ROLE avelren_migrator
    GRANT EXECUTE ON FUNCTIONS TO unexpected_acl_role WITH GRANT OPTION;
SQL
assert_target_check_rejects default-unexpected-grant-option \
    "$WORK/default-unexpected-grant-option.sql" 'target default-privilege'

cat >"$WORK/default-unrelated-role.sql" <<'SQL'
ALTER DEFAULT PRIVILEGES FOR ROLE unexpected_acl_role IN SCHEMA public
    GRANT SELECT ON TABLES TO avelren_watchdog;
SQL
assert_target_check_accepts default-unrelated-role "$WORK/default-unrelated-role.sql"

cat >"$WORK/default-equivalent-regrant.sql" <<'SQL'
ALTER DEFAULT PRIVILEGES FOR ROLE avelren_migrator
    REVOKE EXECUTE ON FUNCTIONS FROM avelren_migrator;
ALTER DEFAULT PRIVILEGES FOR ROLE avelren_migrator
    GRANT EXECUTE ON FUNCTIONS TO avelren_migrator;
ALTER DEFAULT PRIVILEGES FOR ROLE avelren_migrator
    REVOKE USAGE ON TYPES FROM avelren_migrator;
ALTER DEFAULT PRIVILEGES FOR ROLE avelren_migrator
    GRANT USAGE ON TYPES TO avelren_migrator;
SQL
assert_target_check_accepts default-equivalent-regrant "$WORK/default-equivalent-regrant.sql"

cat >"$WORK/residual-non-public-relation.sql" <<'SQL'
CREATE SCHEMA residual_test AUTHORIZATION avelren_admin;
CREATE TABLE residual_test.unexpected_relation(id integer);
ALTER TABLE residual_test.unexpected_relation OWNER TO avelren;
SQL
assert_target_check_rejects residual-non-public-relation \
    "$WORK/residual-non-public-relation.sql" 'target canonical ownership surface mismatch'

cat >"$WORK/residual-routine.sql" <<'SQL'
CREATE SCHEMA residual_test AUTHORIZATION avelren_admin;
CREATE FUNCTION residual_test.unexpected_function() RETURNS integer
    LANGUAGE sql AS 'SELECT 1';
ALTER FUNCTION residual_test.unexpected_function() OWNER TO avelren;
SQL
assert_target_check_rejects residual-routine "$WORK/residual-routine.sql" \
    'target canonical ownership surface mismatch'

cat >"$WORK/residual-type.sql" <<'SQL'
CREATE SCHEMA residual_test AUTHORIZATION avelren_admin;
CREATE TYPE residual_test.unexpected_type AS ENUM ('unexpected');
ALTER TYPE residual_test.unexpected_type OWNER TO avelren;
SQL
assert_target_check_rejects residual-type "$WORK/residual-type.sql" \
    'target canonical ownership surface mismatch'

cat >"$WORK/residual-timescale.sql" <<'SQL'
CREATE TABLE _timescaledb_internal.unexpected_relation(id integer);
ALTER TABLE _timescaledb_internal.unexpected_relation OWNER TO avelren;
SQL
assert_target_check_rejects residual-timescale "$WORK/residual-timescale.sql" \
    'target canonical ownership surface mismatch'

cat >"$WORK/timescale-unexpected-owner.sql" <<'SQL'
ALTER TABLE public.observations OWNER TO unexpected_acl_role;
DO $avelren_tamper$
DECLARE
    mismatched_chunks integer;
BEGIN
    SELECT count(*)
      INTO mismatched_chunks
      FROM _timescaledb_catalog.chunk AS chunk
      JOIN pg_namespace AS namespace ON namespace.nspname = chunk.schema_name
      JOIN pg_class AS relation
        ON relation.relnamespace = namespace.oid
       AND relation.relname = chunk.table_name
     WHERE pg_get_userbyid(relation.relowner) <> 'unexpected_acl_role';
    IF mismatched_chunks <> 0 THEN
        RAISE EXCEPTION 'hypertable owner drift did not reach every real TimescaleDB chunk';
    END IF;
END
$avelren_tamper$;
SQL
assert_target_check_rejects timescale-unexpected-owner \
    "$WORK/timescale-unexpected-owner.sql" 'target .*exact-set mismatch'

cat >"$WORK/residual-shared.sql" <<'SQL'
ALTER DATABASE avelren_residual_test OWNER TO avelren;
SQL
assert_target_check_rejects residual-shared "$WORK/residual-shared.sql" \
    'target canonical ownership surface mismatch'
fi

EVIDENCE="$WORK/evidence"
PREFLIGHT="$WORK/recovery-preflight"
HEAD=$(git -C "$ROOT" rev-parse HEAD)
cat >"$PREFLIGHT" <<EOF
status=PASS
backup_recovery=PASS
exact_commit=$HEAD
EOF
chmod 600 "$PREFLIGHT"

run_adoption() {
    env PATH="$BIN:$PATH" AVELREN_PSQL_BIN="$BIN/psql" AVELREN_DOCKER_BIN="$BIN/docker" \
        ADOPTION_REAL_DOCKER="$REAL_DOCKER" ADOPTION_PROJECT_DIR="$COMPOSE_PROJECT_DIR" \
        ADOPTION_ENV_FILE="$COMPOSE_ENV_FILE" ADOPTION_PROJECT="$PROJECT" \
        ADOPTION_COMPOSE_FILE="$COMPOSE_FILE" ADOPTION_SERVICE_LOG="$WORK/services.log" \
        ADOPTION_SERVICE_STATE="$WORK/services.state" \
        ADOPTION_FORWARD_LOG="$WORK/forward.log" ADOPTION_GATE_LOG="$WORK/gates.log" \
        AVELREN_STACK_DIR="$ROOT" AVELREN_TARGET_DB="$TARGET_DB" \
        AVELREN_ADMIN_DSN="$ADMIN_DSN" AVELREN_EXPECTED_COMMIT="$HEAD" \
        AVELREN_ADMIN_TOOL_DSN="$ADMIN_TOOL_DSN" AVELREN_MIGRATOR_DSN="$MIGRATOR_DSN" \
        AVELREN_BACKUP_DSN="$BACKUP_DSN" AVELREN_COLLECTOR_DSN="$COLLECTOR_DSN" \
        AVELREN_NOTIFIER_DSN="$NOTIFIER_DSN" AVELREN_WATCHDOG_DSN="$WATCHDOG_DSN" \
        AVELREN_API_DSN="$API_DSN" \
        AVELREN_ADOPTION_SUCCESS_GATE_RUNNER="$BIN/success-gate" \
        AVELREN_RECOVERY_PREFLIGHT_FILE="$PREFLIGHT" AVELREN_EVIDENCE_DIR="$EVIDENCE" \
        AVELREN_TEST_DB=1 AVELREN_ALLOW_DIRTY_TEST=1 \
        AVELREN_ADOPTION_FAILPOINT="${ADOPTION_FAILPOINT:-before_commit}" \
        AVELREN_ADOPTION_POST_COMMIT_GATE="${ADOPTION_POST_COMMIT_GATE:-}" \
        AVELREN_ADOPTION_COMMITTED_FAILPOINT="${ADOPTION_COMMITTED_FAILPOINT:-}" \
        AVELREN_ADOPTION_CORRUPT_INVERSE="${ADOPTION_CORRUPT_INVERSE:-0}" \
        ADOPTION_EVIDENCE_FAULT="${ADOPTION_EVIDENCE_FAULT:-}" \
        ADOPTION_NEW_RUNTIME_UP_FAULT="${ADOPTION_NEW_RUNTIME_UP_FAULT:-0}" \
        ADOPTION_NEW_RUNTIME_STOP_FAULT="${ADOPTION_NEW_RUNTIME_STOP_FAULT:-0}" \
        ADOPTION_FAULT_DIR="$WORK" \
        ADOPTION_INVERSE_STAGE_TEST="${ADOPTION_INVERSE_STAGE_TEST:-0}" \
        ADOPTION_INVERSE_STAGE_LOG="$WORK/inverse-stage.log" \
        bash "$ROOT/deploy/postgres-adopt.sh" --confirm-adoption AVELREN-POSTGRES-ADOPTION
}

RETIREMENT_SOAK_FILE=
RETIREMENT_REAL_MKTEMP=
run_retirement() {
    env PATH="$BIN:$PATH" AVELREN_PSQL_BIN="$BIN/psql" \
        ADOPTION_REAL_DOCKER="$REAL_DOCKER" ADOPTION_PROJECT_DIR="$COMPOSE_PROJECT_DIR" \
        ADOPTION_ENV_FILE="$COMPOSE_ENV_FILE" ADOPTION_PROJECT="$PROJECT" \
        ADOPTION_COMPOSE_FILE="$COMPOSE_FILE" \
        AVELREN_TARGET_DB="$TARGET_DB" AVELREN_ADMIN_DSN="$ADMIN_DSN" \
        AVELREN_EXPECTED_COMMIT="$HEAD" AVELREN_RECOVERY_PREFLIGHT_FILE="$PREFLIGHT" \
        AVELREN_EVIDENCE_DIR="$EVIDENCE" AVELREN_TEST_DB=1 AVELREN_ALLOW_DIRTY_TEST=1 \
        AVELREN_ACCEPTED_SOAK_FILE="$RETIREMENT_SOAK_FILE" \
        AVELREN_ADOPTION_RETIREMENT_GATE_RUNNER="$BIN/retirement-gate" \
        AVELREN_MIGRATOR_DSN="$MIGRATOR_DSN" AVELREN_BACKUP_DSN="$BACKUP_DSN" \
        AVELREN_COLLECTOR_DSN="$COLLECTOR_DSN" AVELREN_NOTIFIER_DSN="$NOTIFIER_DSN" \
        AVELREN_WATCHDOG_DSN="$WATCHDOG_DSN" AVELREN_API_DSN="$API_DSN" \
        AVELREN_ADOPTION_FAILPOINT= AVELREN_ADOPTION_POST_COMMIT_GATE= \
        AVELREN_ADOPTION_COMMITTED_FAILPOINT= AVELREN_ADOPTION_CORRUPT_INVERSE=0 \
        AVELREN_RETIREMENT_FAILPOINT="${RETIREMENT_FAILPOINT:-}" \
        ADOPTION_RETIREMENT_ATTEMPT_TEMP_FAULT="${ADOPTION_RETIREMENT_ATTEMPT_TEMP_FAULT:-0}" \
        ADOPTION_REAL_MKTEMP="$RETIREMENT_REAL_MKTEMP" \
        ADOPTION_RETIREMENT_ATTEMPT_TEMP_FAULT_LOG="$WORK/retirement-attempt-temp-fault.log" \
        ADOPTION_RETIREMENT_PUBLISH_TEMP_FAULT_LOG="$WORK/retirement-publish-temp-fault.log" \
        ADOPTION_RETIREMENT_GATE_LOG="$WORK/retirement-gates.log" \
        bash "$ROOT/deploy/postgres-adopt.sh" --confirm-adoption AVELREN-POSTGRES-ADOPTION "$@"
}

run_db_sql() {
    PGPASSWORD="$ADMIN_PASSWORD" real_compose exec -T -e PGPASSWORD db \
        psql -U avelren_admin -d "$TARGET_DB" -v ON_ERROR_STOP=1 -q
}

assert_preflight_rejects_unknown_object() {
    local name=$1 setup=$2 cleanup_sql=$3
    run_db_sql <"$setup"
    rm -rf "$EVIDENCE"
    : >"$WORK/services.log"
    printf '%s\n' running >"$WORK/services.state"
    if run_adoption >"$WORK/$name.out" 2>&1; then
        echo "$name should fail ownership preflight" >&2
        exit 1
    fi
    [ ! -s "$WORK/services.log" ] || {
        echo "$name reached Compose before ownership preflight failed" >&2
        exit 1
    }
    run_db_sql <"$cleanup_sql"
}

if [ "$FOCUSED_CASE" = all ]; then
cat >"$WORK/rogue-timescale-prefix.setup.sql" <<'SQL'
CREATE TABLE _timescaledb_internal.unexpected_preflight_relation(id integer);
ALTER TABLE _timescaledb_internal.unexpected_preflight_relation OWNER TO avelren;
SQL
cat >"$WORK/rogue-timescale-prefix.cleanup.sql" <<'SQL'
DROP TABLE _timescaledb_internal.unexpected_preflight_relation;
SQL
assert_preflight_rejects_unknown_object rogue-timescale-prefix \
    "$WORK/rogue-timescale-prefix.setup.sql" "$WORK/rogue-timescale-prefix.cleanup.sql"

cat >"$WORK/foreign-table.setup.sql" <<'SQL'
CREATE FOREIGN DATA WRAPPER adoption_test_fdw NO HANDLER;
ALTER FOREIGN DATA WRAPPER adoption_test_fdw OWNER TO clusteradmin;
CREATE SERVER adoption_test_server FOREIGN DATA WRAPPER adoption_test_fdw;
ALTER SERVER adoption_test_server OWNER TO clusteradmin;
CREATE FOREIGN TABLE public.unexpected_foreign_table(id integer)
    SERVER adoption_test_server;
ALTER FOREIGN TABLE public.unexpected_foreign_table OWNER TO avelren;
SQL
cat >"$WORK/foreign-table.cleanup.sql" <<'SQL'
DROP FOREIGN TABLE public.unexpected_foreign_table;
DROP SERVER adoption_test_server;
DROP FOREIGN DATA WRAPPER adoption_test_fdw;
SQL
assert_preflight_rejects_unknown_object foreign-table \
    "$WORK/foreign-table.setup.sql" "$WORK/foreign-table.cleanup.sql"

cat >"$WORK/nonpublic-sequence.setup.sql" <<'SQL'
CREATE SCHEMA unexpected_sequence_schema AUTHORIZATION clusteradmin;
CREATE SEQUENCE unexpected_sequence_schema.unexpected_sequence;
ALTER SEQUENCE unexpected_sequence_schema.unexpected_sequence OWNER TO avelren;
SQL
cat >"$WORK/nonpublic-sequence.cleanup.sql" <<'SQL'
DROP SCHEMA unexpected_sequence_schema CASCADE;
SQL
assert_preflight_rejects_unknown_object nonpublic-sequence \
    "$WORK/nonpublic-sequence.setup.sql" "$WORK/nonpublic-sequence.cleanup.sql"

cat >"$WORK/composite-type.setup.sql" <<'SQL'
CREATE TYPE public.unexpected_composite AS (value integer);
ALTER TYPE public.unexpected_composite OWNER TO avelren;
SQL
cat >"$WORK/composite-type.cleanup.sql" <<'SQL'
DROP TYPE public.unexpected_composite CASCADE;
SQL
assert_preflight_rejects_unknown_object composite-type \
    "$WORK/composite-type.setup.sql" "$WORK/composite-type.cleanup.sql"

cat >"$WORK/domain-type.setup.sql" <<'SQL'
CREATE DOMAIN public.unexpected_domain AS integer;
ALTER DOMAIN public.unexpected_domain OWNER TO avelren;
SQL
cat >"$WORK/domain-type.cleanup.sql" <<'SQL'
DROP DOMAIN public.unexpected_domain CASCADE;
SQL
assert_preflight_rejects_unknown_object domain-type \
    "$WORK/domain-type.setup.sql" "$WORK/domain-type.cleanup.sql"

cat >"$WORK/range-types.setup.sql" <<'SQL'
CREATE TYPE public.unexpected_range AS RANGE (
    SUBTYPE = integer,
    MULTIRANGE_TYPE_NAME = public.unexpected_multirange
);
ALTER TYPE public.unexpected_range OWNER TO avelren;
ALTER TYPE public.unexpected_multirange OWNER TO avelren;
SQL
cat >"$WORK/range-types.cleanup.sql" <<'SQL'
DROP TYPE public.unexpected_range CASCADE;
SQL
assert_preflight_rejects_unknown_object range-types \
    "$WORK/range-types.setup.sql" "$WORK/range-types.cleanup.sql"

cat >"$WORK/procedure.setup.sql" <<'SQL'
CREATE PROCEDURE public.unexpected_procedure()
    LANGUAGE SQL AS 'SELECT 1';
ALTER PROCEDURE public.unexpected_procedure() OWNER TO avelren;
SQL
cat >"$WORK/procedure.cleanup.sql" <<'SQL'
DROP PROCEDURE public.unexpected_procedure();
SQL
assert_preflight_rejects_unknown_object procedure \
    "$WORK/procedure.setup.sql" "$WORK/procedure.cleanup.sql"

cat >"$WORK/aggregate.setup.sql" <<'SQL'
CREATE AGGREGATE public.unexpected_aggregate(integer) (
    SFUNC = int4pl,
    STYPE = integer,
    INITCOND = '0'
);
ALTER AGGREGATE public.unexpected_aggregate(integer) OWNER TO avelren;
SQL
cat >"$WORK/aggregate.cleanup.sql" <<'SQL'
DROP AGGREGATE public.unexpected_aggregate(integer);
SQL
assert_preflight_rejects_unknown_object aggregate \
    "$WORK/aggregate.setup.sql" "$WORK/aggregate.cleanup.sql"

# Unknown application relations fail before client stop and before any ownership mutation.
PGPASSWORD="$ADMIN_PASSWORD" real_compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$TARGET_DB" -v ON_ERROR_STOP=1 -q \
    -c 'CREATE TABLE public.unexpected_relation(id integer); ALTER TABLE public.unexpected_relation OWNER TO avelren;'
: >"$WORK/services.log"
if run_adoption >"$WORK/unknown.out" 2>&1; then
    echo 'unexpected application relation should fail closed' >&2
    exit 1
fi
[ ! -s "$WORK/services.log" ] || { echo 'unknown relation reached compose stop' >&2; exit 1; }
unexpected_owner=$(PGPASSWORD="$ADMIN_PASSWORD" real_compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$TARGET_DB" -At \
    -c "SELECT tableowner FROM pg_tables WHERE schemaname='public' AND tablename='unexpected_relation';")
[ "$unexpected_owner" = avelren ] || { echo 'unknown relation ownership was mutated' >&2; exit 1; }
PGPASSWORD="$ADMIN_PASSWORD" real_compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$TARGET_DB" -v ON_ERROR_STOP=1 -q \
    -c 'DROP TABLE public.unexpected_relation;'
fi

# Canonical before_commit scenario must mutate inside one transaction, fail,
# and leave the exact original owner/ACL fingerprint intact with runtime stopped.
: >"$WORK/services.log"
printf '%s\n' running >"$WORK/services.state"
if run_adoption >"$WORK/before-commit.out" 2>&1; then
    echo 'before_commit failpoint should abort adoption' >&2
    exit 1
fi
[ "$(cat "$WORK/services.state")" = stopped ] || {
    echo 'runtime was not left stopped' >&2
    sed -n '1,240p' "$WORK/before-commit.out" >&2 || true
    exit 1
}
grep -q 'stop caddy api collector notifier watchdog' "$WORK/services.log"
! grep -q ' up ' "$WORK/services.log" || { echo 'runtime was optimistically restarted' >&2; exit 1; }

cmp "$EVIDENCE/original.tsv" "$EVIDENCE/after-failure.tsv" || {
    echo 'owner/ACL manifest changed after transactional failure' >&2
    exit 1
}
[ "$(cat "$EVIDENCE/original.sha256")" = "$(cat "$EVIDENCE/after-failure.sha256")" ] || {
    echo 'owner/ACL fingerprint changed after transactional failure' >&2
    exit 1
}
grep -q 'before_commit rollback verified' "$WORK/before-commit.out"
! grep -q 'ci-only' "$WORK/before-commit.out" "$WORK/services.log" || {
    echo 'credential leaked to integration evidence' >&2
    exit 1
}

if [ "${AVELREN_ADOPTION_SCENARIO}" = after_commit ]; then
    assert_refused_before_mutation() {
        local name=$1 failpoint=$2 expected=$3 current_manifest
        current_manifest="$WORK/$name-current.tsv"
        rm -rf "$EVIDENCE"
        : >"$WORK/services.log"
        printf '%s\n' running >"$WORK/services.state"
        if ADOPTION_FAILPOINT="$failpoint" run_adoption >"$WORK/$name.out" 2>&1; then
            echo "$name terminal path should fail closed" >&2
            exit 1
        fi
        grep -q "$expected" "$WORK/$name.out" || {
            echo "$name failed for the wrong reason" >&2
            sed -n '1,160p' "$WORK/$name.out" >&2 || true
            exit 1
        }
        [ "$(cat "$WORK/services.state")" = running ] || {
            echo "$name entered maintenance before refusal" >&2
            exit 1
        }
        [ ! -s "$WORK/services.log" ] || {
            echo "$name reached Compose before refusal" >&2
            exit 1
        }
        [ ! -e "$EVIDENCE/committed-forward.marker" ] || {
            echo "$name committed adoption before refusal" >&2
            exit 1
        }
        AVELREN_TARGET_DB="$TARGET_DB" capture_manifest "$ADMIN_DSN" "$current_manifest"
        cmp "$PLAN_EVIDENCE/original.tsv" "$current_manifest" || {
            echo "$name changed owner or ACL state before refusal" >&2
            exit 1
        }
    }

    assert_verified_rollback_common() {
        local name=$1 output=$2
        [ "$(cat "$WORK/services.state")" = running ] || {
            sed -n '1,260p' "$output" >&2 || true
            echo "$name did not restart previous runtime after exact rollback" >&2
            exit 1
        }
        cmp "$EVIDENCE/original.tsv" "$EVIDENCE/after-failure.tsv" || {
            echo "$name did not restore the exact original manifest" >&2
            exit 1
        }
        cmp "$EVIDENCE/original.sha256" "$EVIDENCE/after-failure.sha256" || {
            echo "$name did not restore the exact original fingerprint" >&2
            exit 1
        }
        grep -q 'post-commit inverse rollback verified' "$output" || {
            echo "$name rollback verification evidence is missing" >&2
            exit 1
        }
        grep -q 'up -d caddy api collector notifier watchdog' "$WORK/services.log" || {
            echo "$name did not restart only after exact verification" >&2
            exit 1
        }
        grep -Fxq 'stage=post_commit_rollback' "$EVIDENCE/stage"
        grep -Fxq 'inverse_verified=PASS' "$EVIDENCE/stage"
    }

    assert_committed_failure_rollback() {
        local failurepoint=$1 output
        output="$WORK/committed-$failurepoint.out"
        rm -rf "$EVIDENCE"
        : >"$WORK/services.log"
        printf '%s\n' running >"$WORK/services.state"
        if ADOPTION_FAILPOINT=after_commit ADOPTION_COMMITTED_FAILPOINT="$failurepoint" \
            run_adoption >"$output" 2>&1; then
            echo "$failurepoint committed failure should return nonzero" >&2
            exit 1
        fi
        grep -q "post-commit $failurepoint FAIL (injected)" "$output" || {
            echo "$failurepoint committed failure injection was not reached" >&2
            sed -n '1,200p' "$output" >&2 || true
            exit 1
        }
        grep -Fxq 'FORWARD_TARGET_VERIFIED' "$EVIDENCE/committed-forward.marker" || {
            echo "$failurepoint did not first commit forward adoption" >&2
            exit 1
        }
        assert_verified_rollback_common "committed-$failurepoint" "$output"
    }

    assert_committed_cleanup_failure() {
        local output current_manifest
        output="$WORK/committed-cleanup.out"
        current_manifest="$WORK/committed-cleanup-current.tsv"
        rm -rf "$EVIDENCE"
        : >"$WORK/services.log"
        : >"$WORK/forward.log"
        printf '%s\n' running >"$WORK/services.state"
        if ADOPTION_FAILPOINT=after_commit ADOPTION_COMMITTED_FAILPOINT=cleanup \
            run_adoption >"$output" 2>&1; then
            echo 'post-COMMIT cleanup failure should return nonzero' >&2
            exit 1
        fi
        grep -q 'committed forward driver cleanup failed after commit (injected)' "$output" || {
            echo 'post-COMMIT cleanup failure injection was not reached' >&2
            sed -n '1,220p' "$output" >&2 || true
            exit 1
        }
        grep -Fxq committed "$WORK/forward.log" || {
            echo 'cleanup failure did not occur after the forward COMMIT' >&2
            exit 1
        }
        cmp "$EVIDENCE/original.tsv" "$EVIDENCE/after-failure.tsv" || {
            echo 'cleanup failure did not restore the exact original manifest' >&2
            exit 1
        }
        cmp "$EVIDENCE/original.sha256" "$EVIDENCE/after-failure.sha256" || {
            echo 'cleanup failure did not restore the exact original fingerprint' >&2
            exit 1
        }
        AVELREN_TARGET_DB="$TARGET_DB" capture_manifest "$ADMIN_DSN" "$current_manifest"
        cmp "$PLAN_EVIDENCE/original.tsv" "$current_manifest" || {
            echo 'cleanup failure left committed owner or ACL state behind' >&2
            exit 1
        }
        [ "$(cat "$WORK/services.state")" = stopped ] || {
            echo 'cleanup failure restarted runtime without committed marker evidence' >&2
            exit 1
        }
        ! grep -q ' up ' "$WORK/services.log" || {
            echo 'cleanup failure attempted restart before the fail-closed boundary' >&2
            exit 1
        }
        [ ! -e "$EVIDENCE/committed-forward.marker" ] || {
            echo 'cleanup failure unexpectedly published committed marker evidence' >&2
            exit 1
        }
        grep -Fxq 'stage=rollback_failed' "$EVIDENCE/stage"
        grep -Fxq 'inverse_verified=PASS' "$EVIDENCE/stage"
        grep -q 'inverse rollback verified but committed marker evidence is unavailable' "$output"
        grep -q 'runtime remains stopped; manual intervention required' "$output"
    }

    assert_post_commit_signal_routes_once() {
        local output current_manifest status route_count
        output="$WORK/post-commit-signal-term.out"
        current_manifest="$WORK/post-commit-signal-term-current.tsv"
        rm -rf "$EVIDENCE"
        : >"$WORK/services.log"
        : >"$WORK/forward.log"
        : >"$WORK/gates.log"
        printf '%s\n' running >"$WORK/services.state"
        set +e
        ADOPTION_FAILPOINT=after_commit ADOPTION_COMMITTED_FAILPOINT=signal_term \
            run_adoption >"$output" 2>&1
        status=$?
        set -e
        [ "$status" -eq 143 ] || {
            echo "post-COMMIT TERM returned $status instead of 143" >&2
            sed -n '1,240p' "$output" >&2 || true
            exit 1
        }
        grep -Fxq committed "$WORK/forward.log" || {
            echo 'TERM did not occur after the forward COMMIT' >&2
            exit 1
        }
        grep -Fxq 'FORWARD_TARGET_VERIFIED' "$EVIDENCE/committed-forward.marker" || {
            echo 'TERM did not reach the deterministic committed marker boundary' >&2
            exit 1
        }
        cmp "$EVIDENCE/original.tsv" "$EVIDENCE/after-failure.tsv" || {
            echo 'TERM did not restore the exact original manifest' >&2
            exit 1
        }
        cmp "$EVIDENCE/original.sha256" "$EVIDENCE/after-failure.sha256" || {
            echo 'TERM did not restore the exact original fingerprint' >&2
            exit 1
        }
        AVELREN_TARGET_DB="$TARGET_DB" capture_manifest "$ADMIN_DSN" "$current_manifest"
        cmp "$PLAN_EVIDENCE/original.tsv" "$current_manifest" || {
            echo 'TERM left committed owner or ACL state behind' >&2
            exit 1
        }
        route_count=$(grep -c 'post-commit failure:' "$output" || true)
        [ "$route_count" -eq 1 ] || {
            echo "TERM invoked post-COMMIT routing $route_count times" >&2
            exit 1
        }
        [ "$(cat "$WORK/services.state")" = running ] || {
            echo 'TERM did not restart the old runtime after exact inverse verification' >&2
            exit 1
        }
        [ "$(grep -c 'up -d caddy api collector notifier watchdog' "$WORK/services.log")" -eq 1 ] || {
            echo 'TERM violated one-restart ordering' >&2
            exit 1
        }
        grep -Fxq 'stage=post_commit_rollback' "$EVIDENCE/stage"
        grep -Fxq 'inverse_verified=PASS' "$EVIDENCE/stage"
        [ "$(adoption_signal_exit_status HUP)" -eq 129 ] || {
            echo 'HUP exit-status mapping is not 129' >&2
            exit 1
        }
        [ "$(adoption_signal_exit_status INT)" -eq 130 ] || {
            echo 'INT exit-status mapping is not 130' >&2
            exit 1
        }
        [ "$(adoption_signal_exit_status TERM)" -eq 143 ] || {
            echo 'TERM exit-status mapping is not 143' >&2
            exit 1
        }
    }

    assert_after_commit_rollback() {
        local gate=$1 hash_test=${2:-0} output original_fingerprint committed_fingerprint
        local expected_privilege expected_isolation expected_smoke expected_freshness expected_gate
        output="$WORK/after-commit-$gate.out"
        if [ "$hash_test" = 1 ]; then
            local atomic_dir="$WORK/atomic-fingerprint" atomic_victim="$WORK/atomic-victim"
            rm -rf "$atomic_dir"
            prepare_evidence_dir "$atomic_dir"
            printf '%s\n' atomic-sentinel >"$atomic_victim"
            make_unsafe_link "$atomic_victim" "$atomic_dir/fingerprint.sha256"
            assert_unsafe_link_platform "$atomic_dir/fingerprint.sha256"
            if ! publish_manifest_fingerprint "$PLAN_EVIDENCE/original.tsv" \
                "$atomic_dir/fingerprint.sha256"; then
                echo "$gate atomic fingerprint publication is unavailable" >&2
                exit 1
            fi
            [ "$(cat "$atomic_victim")" = atomic-sentinel ] || {
                echo "$gate atomic fingerprint publication followed a symlink" >&2
                exit 1
            }
            [ ! -L "$atomic_dir/fingerprint.sha256" ] || {
                echo "$gate atomic fingerprint publication retained a symlink" >&2
                exit 1
            }
            [ "$(stat -c '%a' "$atomic_dir/fingerprint.sha256")" = 600 ]
        fi
        rm -rf "$EVIDENCE"
        : >"$WORK/services.log"
        : >"$WORK/gates.log"
        printf '%s\n' running >"$WORK/services.state"
        if ADOPTION_FAILPOINT=after_commit ADOPTION_POST_COMMIT_GATE="$gate" \
            run_adoption >"$output" 2>&1; then
            echo "$gate post-commit failure should trigger inverse rollback" >&2
            exit 1
        fi
        grep -q 'committed forward adoption verified' "$output" || {
            echo "$gate did not prove committed forward adoption" >&2
            sed -n '1,240p' "$output" >&2 || true
            exit 1
        }
        grep -Fxq 'FORWARD_TARGET_VERIFIED' "$EVIDENCE/committed-forward.marker"
        original_fingerprint=$(manifest_fingerprint "$EVIDENCE/original.tsv")
        committed_fingerprint=$(manifest_fingerprint "$EVIDENCE/committed.tsv")
        [ "$original_fingerprint" != "$committed_fingerprint" ] || {
            echo "$gate forward adoption was not a committed catalog change" >&2
            exit 1
        }
        assert_verified_rollback_common "$gate" "$output"
        [ "$(stat -c '%a' "$EVIDENCE")" = 700 ]
        [ "$(stat -c '%a' "$EVIDENCE/stage")" = 600 ]
        : >"$WORK/expected-preceding-gates"
        for expected_gate in migrate privilege_contracts compose_credential_switch smoke collector_freshness environment_isolation; do
            [ "$expected_gate" = "$gate" ] && break
            printf '%s\n' "$expected_gate" >>"$WORK/expected-preceding-gates"
        done
        cmp "$WORK/expected-preceding-gates" "$WORK/gates.log" || {
            echo "$gate did not run exactly the preceding real gate callbacks" >&2
            exit 1
        }
        expected_privilege=NOT_RUN
        expected_isolation=NOT_RUN
        expected_smoke=NOT_RUN
        expected_freshness=NOT_RUN
        case "$gate" in
            migrate) ;;
            privilege_contracts) expected_privilege=FAIL ;;
            compose_credential_switch) expected_privilege=PASS ;;
            smoke) expected_privilege=PASS; expected_smoke=FAIL ;;
            collector_freshness) expected_privilege=PASS; expected_smoke=PASS; expected_freshness=FAIL ;;
            environment_isolation)
                expected_privilege=PASS
                expected_smoke=PASS
                expected_freshness=PASS
                expected_isolation=FAIL
                ;;
        esac
        grep -Fxq "privilege_contract_result=$expected_privilege" "$EVIDENCE/stage"
        grep -Fxq "environment_isolation_result=$expected_isolation" "$EVIDENCE/stage"
        grep -Fxq "smoke_result=$expected_smoke" "$EVIDENCE/stage"
        grep -Fxq "freshness_result=$expected_freshness" "$EVIDENCE/stage"
        grep -Fxq 'accepted_cutover=NOT_RUN' "$EVIDENCE/stage"
        ! grep -Eq '^(schema_verification|application_dml|application_verification|freshness_write|freshness_verification)_role=avelren_admin$' \
            "$output" || { echo "$gate used admin for a least-credential gate" >&2; exit 1; }
        if [ "$gate" = environment_isolation ]; then
            for expected_gate in \
                schema_verification_role=avelren_migrator \
                application_dml_role=avelren_migrator \
                application_verification_role=avelren_api \
                freshness_write_role=avelren_collector \
                freshness_verification_role=avelren_watchdog; do
                grep -Fxq "$expected_gate" "$output" || {
                    echo "late failure lacks least-credential proof: $expected_gate" >&2
                    exit 1
                }
            done
        fi
    }

    assert_parent_evidence_directory_refused() {
        local victim="$WORK/evidence-parent-victim" victim_mode current_manifest failures=0
        current_manifest="$WORK/evidence-parent-current.tsv"
        rm -rf "$EVIDENCE" "$victim"
        mkdir "$victim"
        chmod 750 "$victim"
        printf '%s\n' parent-sentinel >"$victim/sentinel"
        victim_mode=$(stat -c '%a' "$victim")
        make_unsafe_directory_link "$victim" "$EVIDENCE"
        assert_unsafe_directory_link_platform "$EVIDENCE"
        if publish_manifest_fingerprint "$PLAN_EVIDENCE/original.tsv" "$EVIDENCE/fingerprint.sha256" \
            >"$WORK/evidence-parent.out" 2>&1; then
            echo 'symlinked parent evidence directory was accepted' >&2
            failures=$((failures + 1))
        fi
        [ ! -e "$victim/fingerprint.sha256" ] || {
            echo 'publisher wrote through the parent evidence-directory link' >&2
            failures=$((failures + 1))
        }
        [ "$(cat "$victim/sentinel")" = parent-sentinel ] || {
            echo 'publisher changed data outside the intended evidence directory' >&2
            failures=$((failures + 1))
        }
        [ "$(stat -c '%a' "$victim")" = "$victim_mode" ] || {
            echo 'publisher chmod followed the parent evidence-directory link' >&2
            failures=$((failures + 1))
        }
        rm -f -- "$EVIDENCE" || { echo 'cannot remove unsafe parent fixture' >&2; exit 1; }
        AVELREN_TARGET_DB="$TARGET_DB" capture_manifest "$ADMIN_DSN" "$current_manifest"
        cmp "$PLAN_EVIDENCE/original.tsv" "$current_manifest" || {
            echo 'parent evidence-directory rejection changed role ownership state' >&2
            failures=$((failures + 1))
        }
        [ "$failures" -eq 0 ] || exit 1
    }

    assert_publisher_validation_rejects_malformed_success() {
        local directory="$WORK/publisher-validation" stage retirement fingerprint current_manifest
        local failures=0 legacy_login
        directory="$WORK/publisher-validation"
        stage="$directory/stage"
        retirement="$directory/legacy-retirement"
        current_manifest="$WORK/publisher-validation-current.tsv"
        rm -rf "$directory"
        prepare_evidence_dir "$directory"
        fingerprint=$(manifest_fingerprint "$PLAN_EVIDENCE/original.tsv")
        if publish_adoption_stage "$stage" malformed committed "$fingerprint" - \
            NOT_RUN NOT_RUN NOT_RUN NOT_RUN NOT_RUN; then
            echo 'malformed stage SHA published success' >&2
            failures=$((failures + 1))
        fi
        [ ! -e "$stage" ] || { echo 'malformed stage evidence survived publication' >&2; failures=$((failures + 1)); }
        if publish_adoption_stage "$stage" "$HEAD" committed malformed - \
            NOT_RUN NOT_RUN NOT_RUN NOT_RUN NOT_RUN; then
            echo 'malformed stage fingerprint published success' >&2
            failures=$((failures + 1))
        fi
        [ ! -e "$stage" ] || { echo 'malformed fingerprint stage evidence survived' >&2; failures=$((failures + 1)); }
        publish_legacy_retirement_attempt "$retirement" "$HEAD"
        if publish_legacy_retirement "$retirement" malformed "$fingerprint" "$fingerprint" \
            PASS PASS PASS; then
            echo 'malformed retirement SHA published success' >&2
            failures=$((failures + 1))
        fi
        ! grep -Fxq 'stage=legacy_retired' "$retirement" || {
            echo 'malformed retirement SHA left authoritative success' >&2
            failures=$((failures + 1))
        }
        rm -f "$retirement"
        publish_legacy_retirement_attempt "$retirement" "$HEAD"
        if publish_legacy_retirement "$retirement" "$HEAD" "$fingerprint" \
            0000000000000000000000000000000000000000000000000000000000000000 \
            PASS PASS PASS; then
            echo 'mismatched retirement fingerprint published success' >&2
            failures=$((failures + 1))
        fi
        ! grep -Fxq 'stage=legacy_retired' "$retirement" || {
            echo 'mismatched retirement fingerprint left authoritative success' >&2
            failures=$((failures + 1))
        }
        legacy_login=$(PGPASSWORD="$ADMIN_PASSWORD" real_compose exec -T -e PGPASSWORD db \
            psql -U avelren_admin -d "$TARGET_DB" -At -v ON_ERROR_STOP=1 \
            -c "SELECT rolcanlogin FROM pg_roles WHERE rolname='avelren';")
        [ "$legacy_login" = t ] || {
            echo 'pre-mutation publisher validation changed legacy LOGIN state' >&2
            failures=$((failures + 1))
        }
        AVELREN_TARGET_DB="$TARGET_DB" capture_manifest "$ADMIN_DSN" "$current_manifest"
        cmp "$PLAN_EVIDENCE/original.tsv" "$current_manifest" || {
            echo 'pre-mutation publisher validation changed owner or ACL state' >&2
            failures=$((failures + 1))
        }
        [ "$failures" -eq 0 ] || exit 1
    }

    assert_post_commit_evidence_failure() {
        local fault=$1 output current_manifest expected_inverse
        output="$WORK/evidence-failure-$fault.out"
        current_manifest="$WORK/evidence-failure-$fault.tsv"
        expected_inverse=FAIL
        assert_original_disposable_state "evidence-failure-$fault"
        rm -rf "$EVIDENCE"
        prepare_evidence_dir "$EVIDENCE"
        rm -f "$WORK/fail-next-capture"
        case "$fault" in
            committed_marker)
                mkdir "$EVIDENCE/committed-forward.marker"
                expected_inverse=PASS
                ;;
            rollback_recapture)
                cp "$PLAN_EVIDENCE/original.tsv" "$EVIDENCE/after-failure.tsv"
                ;;
            rollback_fingerprint)
                mkdir "$EVIDENCE/after-failure.sha256"
                ;;
            *) echo 'unknown post-commit evidence fault' >&2; exit 1 ;;
        esac
        : >"$WORK/services.log"
        printf '%s\n' running >"$WORK/services.state"
        if ADOPTION_FAILPOINT=after_commit ADOPTION_POST_COMMIT_GATE=smoke \
            ADOPTION_EVIDENCE_FAULT="$fault" run_adoption >"$output" 2>&1; then
            echo "$fault evidence failure must return nonzero" >&2
            exit 1
        fi
        [ "$(cat "$WORK/services.state")" = stopped ] || {
            echo "$fault evidence failure restarted the previous runtime" >&2
            sed -n '1,220p' "$output" >&2 || true
            exit 1
        }
        ! grep -q ' up ' "$WORK/services.log" || {
            echo "$fault evidence failure invoked an optimistic restart" >&2
            exit 1
        }
        grep -q 'manual intervention required' "$output" || {
            echo "$fault evidence failure omitted manual-intervention output" >&2
            exit 1
        }
        AVELREN_TARGET_DB="$TARGET_DB" capture_manifest "$ADMIN_DSN" "$current_manifest"
        cmp "$PLAN_EVIDENCE/original.tsv" "$current_manifest" || {
            echo "$fault evidence failure did not preserve the restored original state" >&2
            exit 1
        }
        grep -Fxq 'stage=rollback_failed' "$EVIDENCE/stage" || {
            echo "$fault evidence failure published a false success stage" >&2
            exit 1
        }
        grep -Fxq "inverse_verified=$expected_inverse" "$EVIDENCE/stage" || {
            echo "$fault evidence failure published an untruthful inverse result" >&2
            exit 1
        }
    }

    assert_original_disposable_state() {
        local name=$1 current_manifest
        current_manifest="$WORK/before-$name.tsv"
        AVELREN_TARGET_DB="$TARGET_DB" capture_manifest "$ADMIN_DSN" "$current_manifest"
        cmp "$PLAN_EVIDENCE/original.tsv" "$current_manifest" || {
            echo "$name did not start from the proven original disposable state" >&2
            exit 1
        }
    }

    restore_original_disposable_state() {
        local reset_driver reset_output
        reset_driver="$WORK/corrupt-case-reset.sql"
        reset_output="$WORK/corrupt-case-reset.out"
        {
            printf '%s\n' '\set ON_ERROR_STOP on' 'BEGIN;'
            cat "$EVIDENCE/inverse.sql"
            printf '%s\n' 'COMMIT;'
        } >"$reset_driver"
        run_db_sql <"$reset_driver" >"$reset_output" 2>&1 || {
            echo 'failed to restore the disposable corruption fixture' >&2
            sed -n '1,160p' "$reset_output" >&2 || true
            exit 1
        }
        assert_original_disposable_state corrupt-case-reset
    }

    assert_corrupt_inverse() {
        local mode=$1 stage_test=${2:-0} output current_manifest
        output="$WORK/corrupt-$mode.out"
        current_manifest="$WORK/after-corrupt-$mode.tsv"
        assert_original_disposable_state "corrupt-$mode"
        rm -rf "$EVIDENCE"
        rm -f "$WORK/inverse-stage.log"
        : >"$WORK/services.log"
        printf '%s\n' running >"$WORK/services.state"
        if ADOPTION_FAILPOINT=after_commit ADOPTION_POST_COMMIT_GATE=smoke \
            ADOPTION_CORRUPT_INVERSE="$mode" ADOPTION_INVERSE_STAGE_TEST="$stage_test" \
            run_adoption >"$output" 2>&1; then
            echo "$mode corrupt inverse must fail closed" >&2
            exit 1
        fi
        grep -q 'committed forward adoption verified' "$output" || {
            echo "$mode corrupt inverse did not first commit forward adoption" >&2
            exit 1
        }
        AVELREN_TARGET_DB="$TARGET_DB" capture_manifest "$ADMIN_DSN" "$current_manifest"
        cmp "$EVIDENCE/committed.tsv" "$current_manifest" || {
            echo "$mode corrupt inverse committed a partial third state" >&2
            exit 1
        }
        ! cmp -s "$EVIDENCE/original.tsv" "$current_manifest" || {
            echo "$mode corrupt inverse did not preserve committed target state" >&2
            exit 1
        }
        [ "$(cat "$WORK/services.state")" = stopped ] || {
            echo "$mode corrupt inverse restarted previous runtime" >&2
            exit 1
        }
        ! grep -q ' up ' "$WORK/services.log" || {
            echo "$mode corrupt inverse performed an optimistic restart" >&2
            exit 1
        }
        grep -q 'manual intervention required' "$output"
        grep -Fxq 'stage=rollback_failed' "$EVIDENCE/stage"
        grep -Fxq 'inverse_verified=FAIL' "$EVIDENCE/stage"
        if [ "$stage_test" = 1 ]; then
            grep -Fxq PASS "$WORK/inverse-stage.log" || {
                echo "$mode inverse did not begin from inverse_verified=NOT_RUN" >&2
                exit 1
            }
        fi
        if [ "$mode" = incomplete ]; then
            grep -q 'inverse rollback exact manifest mismatch' "$output" || {
                echo 'incomplete inverse failed for the wrong reason' >&2
                exit 1
            }
        fi
    }

    case "$FOCUSED_CASE" in
        all|terminal)
            assert_refused_before_mutation after-without-gate after_commit \
                'after_commit requires exactly one injected post-commit failure'
            assert_refused_before_mutation unsupported-scenario unsupported \
                'adoption failpoint must be before_commit, after_commit, or success'
            ;;
    esac
    case "$FOCUSED_CASE" in all|committed_capture) assert_committed_failure_rollback capture ;; esac
    case "$FOCUSED_CASE" in all|committed_verification) assert_committed_failure_rollback verification ;; esac
    case "$FOCUSED_CASE" in all|committed_cleanup) assert_committed_cleanup_failure ;; esac
    case "$FOCUSED_CASE" in all|signal_term) assert_post_commit_signal_routes_once ;; esac
    case "$FOCUSED_CASE" in all|evidence_parent) assert_parent_evidence_directory_refused ;; esac
    case "$FOCUSED_CASE" in all|publisher_validation) assert_publisher_validation_rejects_malformed_success ;; esac
    case "$FOCUSED_CASE" in
        all)
            for gate in migrate privilege_contracts compose_credential_switch smoke collector_freshness environment_isolation; do
                if [ "$gate" = migrate ]; then
                    assert_after_commit_rollback "$gate" 1
                else
                    assert_after_commit_rollback "$gate"
                fi
            done
            ;;
        gate_atomic) assert_after_commit_rollback migrate 1 ;;
        late_gates) assert_after_commit_rollback environment_isolation ;;
    esac
    case "$FOCUSED_CASE" in all|committed_marker) assert_post_commit_evidence_failure committed_marker ;; esac
    case "$FOCUSED_CASE" in all|rollback_recapture) assert_post_commit_evidence_failure rollback_recapture ;; esac
    case "$FOCUSED_CASE" in all|rollback_fingerprint) assert_post_commit_evidence_failure rollback_fingerprint ;; esac
    case "$FOCUSED_CASE" in all|invalid_inverse) assert_corrupt_inverse invalid_sql 1 ;; esac
    if [ "$FOCUSED_CASE" = all ]; then
        restore_original_disposable_state
    fi
    case "$FOCUSED_CASE" in all|incomplete_inverse) assert_corrupt_inverse incomplete ;; esac

    echo "postgres adoption after_commit integration ($FOCUSED_CASE): PASS"
elif [ "${AVELREN_ADOPTION_SCENARIO}" = success ]; then
    assert_startup_stop_failure_routes_inverse() {
        local output current_manifest status route_count
        output="$WORK/startup-stop-failure.out"
        current_manifest="$WORK/startup-stop-failure-current.tsv"
        rm -rf "$EVIDENCE"
        rm -f "$WORK/startup-up-fault-consumed" "$WORK/startup-stop-fault-consumed"
        : >"$WORK/services.log"
        : >"$WORK/forward.log"
        : >"$WORK/gates.log"
        printf '%s\n' running >"$WORK/services.state"
        set +e
        ADOPTION_FAILPOINT=success ADOPTION_NEW_RUNTIME_UP_FAULT=1 \
            ADOPTION_NEW_RUNTIME_STOP_FAULT=1 run_adoption >"$output" 2>&1
        status=$?
        set -e
        [ "$status" -ne 0 ] || {
            echo 'startup plus immediate stop failure unexpectedly succeeded' >&2
            exit 1
        }
        grep -q 'new runtime startup failure injected' "$output" || {
            echo 'new runtime startup failure injection was not reached' >&2
            exit 1
        }
        grep -q 'new runtime stop failure injected' "$output" || {
            echo 'immediate new runtime stop failure injection was not reached' >&2
            exit 1
        }
        grep -Fxq committed "$WORK/forward.log" || {
            echo 'startup failure did not first commit forward adoption' >&2
            exit 1
        }
        cmp "$EVIDENCE/original.tsv" "$EVIDENCE/after-failure.tsv" || {
            echo 'startup stop failure did not restore the exact original manifest' >&2
            exit 1
        }
        cmp "$EVIDENCE/original.sha256" "$EVIDENCE/after-failure.sha256" || {
            echo 'startup stop failure did not restore the exact original fingerprint' >&2
            exit 1
        }
        AVELREN_TARGET_DB="$TARGET_DB" capture_manifest "$ADMIN_DSN" "$current_manifest"
        cmp "$PLAN_EVIDENCE/original.tsv" "$current_manifest" || {
            echo 'startup stop failure left committed owner or ACL state behind' >&2
            exit 1
        }
        route_count=$(grep -c 'post-commit failure:' "$output" || true)
        [ "$route_count" -eq 1 ] || {
            echo "startup stop failure invoked post-COMMIT routing $route_count times" >&2
            exit 1
        }
        [ "$(cat "$WORK/services.state")" = stopped ] || {
            echo 'startup stop failure did not retain maintenance state' >&2
            exit 1
        }
        [ "$(grep -c 'up -d caddy api collector notifier watchdog' "$WORK/services.log")" -eq 1 ] || {
            echo 'startup stop failure attempted an old-runtime restart' >&2
            exit 1
        }
        grep -Fxq 'stage=rollback_failed' "$EVIDENCE/stage"
        grep -Fxq 'inverse_verified=PASS' "$EVIDENCE/stage"
        grep -q 'new-runtime stop was not confirmed' "$output" || {
            echo 'startup stop failure omitted the no-restart reason' >&2
            exit 1
        }
        grep -q 'manual intervention required' "$output" || {
            echo 'startup stop failure omitted manual-intervention evidence' >&2
            exit 1
        }
        ! grep -q 'successful committed adoption complete' "$output" || {
            echo 'startup stop failure claimed cutover success' >&2
            exit 1
        }
    }

    case "$FOCUSED_CASE" in
        all|startup_stop_failure) assert_startup_stop_failure_routes_inverse ;;
    esac
    if [ "$FOCUSED_CASE" = startup_stop_failure ]; then
        echo 'postgres adoption startup-stop failure integration: PASS'
        exit 0
    fi
    printf '%s\n' running >"$WORK/services.state"
    rm -rf "$EVIDENCE"
    prepare_evidence_dir "$EVIDENCE"
    printf '%s\n' stage-symlink-sentinel >"$WORK/stage-symlink-victim"
    make_unsafe_link "$WORK/stage-symlink-victim" "$EVIDENCE/stage"
    assert_unsafe_link_platform "$EVIDENCE/stage"
    : >"$WORK/services.log"
    : >"$WORK/forward.log"
    : >"$WORK/gates.log"
    printf '%s\n' running >"$WORK/services.state"

    if ! ADOPTION_FAILPOINT=success run_adoption >"$WORK/success.out" 2>&1; then
        echo 'success adoption scenario should complete' >&2
        sed -n '1,280p' "$WORK/success.out" >&2 || true
        exit 1
    fi

    [ "$(cat "$WORK/services.state")" = running ] || {
        echo 'success cutover did not start the new runtime' >&2
        exit 1
    }
    [ "$(wc -l <"$WORK/forward.log")" -eq 1 ] || {
        echo 'success cutover did not commit forward adoption exactly once' >&2
        exit 1
    }
    cat >"$WORK/expected-success-gates" <<'EOF'
migrate
privilege_contracts
compose_credential_switch
smoke
collector_freshness
environment_isolation
EOF
    cmp "$WORK/expected-success-gates" "$WORK/gates.log" || {
        echo 'success gates did not pass in the frozen order' >&2
        exit 1
    }
    [ "$(grep -c 'up -d caddy api collector notifier watchdog' "$WORK/services.log")" -eq 1 ] || {
        echo 'new runtime was not started exactly once after success gates' >&2
        exit 1
    }
    if ! grep -Fxq 'schema_verification_role=avelren_migrator' "$WORK/success.out" ||
       ! grep -Fxq 'application_dml_role=avelren_migrator' "$WORK/success.out" ||
       ! grep -Fxq 'application_verification_role=avelren_api' "$WORK/success.out" ||
       grep -Eq '^(schema_verification|application_dml|application_verification)_role=avelren_admin$' \
           "$WORK/success.out"; then
        echo 'admin DSN was used for application DML, schema verification, or application verification' >&2
        exit 1
    fi

    grep -Fxq 'stage=cutover_complete' "$EVIDENCE/stage"
    grep -Fxq 'inverse_verified=NOT_RUN' "$EVIDENCE/stage"
    grep -Fxq 'privilege_contract_result=PASS' "$EVIDENCE/stage"
    grep -Fxq 'environment_isolation_result=PASS' "$EVIDENCE/stage"
    grep -Fxq 'smoke_result=PASS' "$EVIDENCE/stage"
    grep -Fxq 'freshness_result=PASS' "$EVIDENCE/stage"
    grep -Fxq 'accepted_cutover=PASS' "$EVIDENCE/stage"
    [ "$(cat "$WORK/stage-symlink-victim")" = stage-symlink-sentinel ] || {
        echo 'success evidence followed the stage symlink' >&2
        exit 1
    }
    [ ! -L "$EVIDENCE/stage" ] || { echo 'success evidence retained a stage symlink' >&2; exit 1; }
    [ "$(stat -c '%a' "$EVIDENCE")" = 700 ]
    while IFS= read -r evidence_file; do
        [ "$(stat -c '%a' "$evidence_file")" = 600 ] || {
            echo "success evidence file is not mode 0600: $evidence_file" >&2
            exit 1
        }
        [ ! -L "$evidence_file" ] || {
            echo "success evidence contains a symlink: $evidence_file" >&2
            exit 1
        }
    done < <(find "$EVIDENCE" -maxdepth 1 -type f -print)
    ! grep -R -E 'ci-only|postgresql://|DATABASE_URL|PASSWORD' "$EVIDENCE" || {
        echo 'success evidence contains credential material' >&2
        exit 1
    }

    owner_contract=$(PGPASSWORD="$ADMIN_PASSWORD" real_compose exec -T -e PGPASSWORD db \
        psql -U avelren_admin -d "$TARGET_DB" -At -F '|' -v ON_ERROR_STOP=1 -c \
        "SELECT pg_get_userbyid(d.datdba), pg_get_userbyid(n.nspowner), pg_get_userbyid(e.extowner), (SELECT count(*) FROM pg_shdepend sd JOIN pg_roles r ON r.oid=sd.refobjid WHERE sd.refclassid='pg_authid'::regclass AND sd.deptype='o' AND r.rolname='avelren' AND (sd.dbid=0 OR sd.dbid=(SELECT oid FROM pg_database WHERE datname=current_database()))), (SELECT rolcanlogin FROM pg_roles WHERE rolname='avelren') FROM pg_database d CROSS JOIN pg_namespace n CROSS JOIN pg_extension e WHERE d.datname=current_database() AND n.nspname='public' AND e.extname='timescaledb';")
    [ "$owner_contract" = 'avelren_admin|avelren_admin|avelren_admin|0|t' ] || {
        echo "success owner or legacy-role contract mismatch: $owner_contract" >&2
        exit 1
    }
    AVELREN_TARGET_DB="$TARGET_DB" verify_target_ownership "$ADMIN_DSN" "$EVIDENCE/original.tsv"

    if [ "$RETIRE_LEGACY_TEST" = 1 ]; then
        SOAK_DIR="$WORK/accepted-soak"
        mkdir -p "$SOAK_DIR"
        chmod 700 "$SOAK_DIR"
        RETIREMENT_SOAK_FILE="$SOAK_DIR/accepted"
        retirement_failures=0
        retirement_now=$(date -u +%s)
        retirement_target_fingerprint=$(cat "$EVIDENCE/stage" | \
            sed -n 's/^target_fingerprint=//p')
        : >"$UNSAFE_LINK_MODE_LOG"
        RETIREMENT_REAL_MKTEMP=$(command -v mktemp)
        cat >"$BIN/mktemp" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [ "${ADOPTION_RETIREMENT_ATTEMPT_TEMP_FAULT:-0}" = 1 ]; then
    printf '%s\n' 'initial retirement attempt temp failure injected' \
        >"$ADOPTION_RETIREMENT_ATTEMPT_TEMP_FAULT_LOG"
    exit 73
fi
if [ "${AVELREN_RETIREMENT_PUBLISH_CONTEXT:-}" = final ] && \
   [ "${AVELREN_RETIREMENT_FAILPOINT:-}" = publication ]; then
    printf '%s\n' 'final retirement publisher mktemp failure injected' \
        >"$ADOPTION_RETIREMENT_PUBLISH_TEMP_FAULT_LOG"
    exit 74
fi
exec "$ADOPTION_REAL_MKTEMP" "$@"
SH
        chmod 700 "$BIN/mktemp"

        record_retirement_failure() {
            echo "retirement assertion failed: $*" >&2
            retirement_failures=$((retirement_failures + 1))
        }

        legacy_login_state() {
            PGPASSWORD="$ADMIN_PASSWORD" real_compose exec -T -e PGPASSWORD db \
                psql -U avelren_admin -d "$TARGET_DB" -At -v ON_ERROR_STOP=1 \
                -c "SELECT rolcanlogin FROM pg_roles WHERE rolname='avelren';"
        }

        reset_legacy_login() {
            PGPASSWORD="$ADMIN_PASSWORD" real_compose exec -T -e PGPASSWORD db \
                psql -U avelren_admin -d "$TARGET_DB" -q -v ON_ERROR_STOP=1 \
                -c 'ALTER ROLE avelren LOGIN;'
        }

        write_soak_marker() {
            local accepted=$1 commit=$2 fingerprint=$3 accepted_at=$4
            cat >"$RETIREMENT_SOAK_FILE" <<EOF
accepted_soak=$accepted
exact_commit=$commit
target_fingerprint=$fingerprint
accepted_at_epoch=$accepted_at
EOF
            chmod 600 "$RETIREMENT_SOAK_FILE"
        }

        seed_stale_retirement_success() {
            rm -f "$EVIDENCE/legacy-retirement"
            cat >"$EVIDENCE/legacy-retirement" <<EOF
exact_commit=$HEAD
stage=legacy_retired
target_fingerprint=$retirement_target_fingerprint
post_retirement_fingerprint=$retirement_target_fingerprint
legacy_credential_retired=PASS
privilege_contract_result=PASS
environment_isolation_result=PASS
accepted_soak=PASS
EOF
            chmod 600 "$EVIDENCE/legacy-retirement"
        }

        assert_retirement_attempt_invalidated() {
            local name=$1
            validate_protected_evidence_file "$EVIDENCE/legacy-retirement" \
                'retirement attempt evidence' >/dev/null 2>&1 || \
                record_retirement_failure "$name did not leave protected attempt evidence"
            grep -Fxq "exact_commit=$HEAD" "$EVIDENCE/legacy-retirement" || \
                record_retirement_failure "$name attempt evidence has the wrong commit"
            grep -Fxq 'stage=legacy_retirement_in_progress' "$EVIDENCE/legacy-retirement" || \
                record_retirement_failure "$name left stale legacy_retired evidence claimable"
            grep -Fxq 'legacy_credential_retired=NOT_VERIFIED' "$EVIDENCE/legacy-retirement" || \
                record_retirement_failure "$name left stale retirement PASS claimable"
            ! grep -Fxq 'stage=legacy_retired' "$EVIDENCE/legacy-retirement" || \
                record_retirement_failure "$name retained a legacy_retired stage"
            ! grep -Fxq 'legacy_credential_retired=PASS' "$EVIDENCE/legacy-retirement" || \
                record_retirement_failure "$name retained retirement PASS"
        }

        assert_retirement_refused() {
            local name=$1 expected=$2 output current_manifest
            output="$WORK/retirement-$name.out"
            current_manifest="$WORK/retirement-$name.tsv"
            seed_stale_retirement_success
            rm -f "$EVIDENCE/retirement-after.tsv"
            : >"$WORK/retirement-gates.log"
            if run_retirement --retire-legacy >"$output" 2>&1; then
                record_retirement_failure "$name unexpectedly succeeded"
            elif ! grep -q "$expected" "$output"; then
                record_retirement_failure "$name failed for the wrong reason"
                sed -n '1,100p' "$output" >&2 || true
            fi
            [ "$(legacy_login_state)" = t ] || \
                record_retirement_failure "$name changed legacy LOGIN before prerequisites passed"
            assert_retirement_attempt_invalidated "$name"
            AVELREN_TARGET_DB="$TARGET_DB" capture_manifest "$ADMIN_DSN" "$current_manifest"
            cmp -s "$EVIDENCE/committed.tsv" "$current_manifest" || \
                record_retirement_failure "$name changed the canonical owner/ACL fingerprint"
        }

        assert_retirement_failure() {
            local name=$1 failpoint=$2 expected=$3 expected_login=$4 output
            output="$WORK/retirement-$name.out"
            seed_stale_retirement_success
            rm -f "$EVIDENCE/retirement-after.tsv"
            : >"$WORK/retirement-gates.log"
            if RETIREMENT_FAILPOINT="$failpoint" run_retirement --retire-legacy >"$output" 2>&1; then
                record_retirement_failure "$name unexpectedly succeeded"
            elif ! grep -q "$expected" "$output"; then
                record_retirement_failure "$name failed for the wrong reason"
                sed -n '1,100p' "$output" >&2 || true
            fi
            [ "$(legacy_login_state)" = "$expected_login" ] || \
                record_retirement_failure "$name left the wrong legacy LOGIN state"
            assert_retirement_attempt_invalidated "$name"
            if [ "$failpoint" = publication ]; then
                grep -Fxq 'final retirement publisher mktemp failure injected' \
                    "$WORK/retirement-publish-temp-fault.log" || \
                    record_retirement_failure \
                        'final publication failure did not reach the real mktemp boundary'
                grep -q 'manual intervention required' "$output" || \
                    record_retirement_failure \
                        'final publication failure omitted truthful manual-intervention state'
                ! grep -q 'legacy retirement complete' "$output" || \
                    record_retirement_failure 'final publication failure claimed success'
            fi
        }

        [ "$(legacy_login_state)" = t ] || \
            record_retirement_failure 'normal success without --retire-legacy retired the legacy role'
        [ ! -e "$EVIDENCE/legacy-retirement" ] || \
            record_retirement_failure 'normal success published retirement evidence without the explicit flag'

        write_soak_marker PASS "$HEAD" "$retirement_target_fingerprint" "$retirement_now"
        seed_stale_retirement_success
        rm -f "$WORK/retirement-attempt-temp-fault.log"
        if ADOPTION_RETIREMENT_ATTEMPT_TEMP_FAULT=1 run_retirement --retire-legacy \
            >"$WORK/retirement-attempt-temp-failure.out" 2>&1; then
            record_retirement_failure 'initial attempt temp failure unexpectedly succeeded'
        elif ! grep -q 'retirement attempt evidence temporary file creation failed' \
            "$WORK/retirement-attempt-temp-failure.out"; then
            record_retirement_failure 'initial attempt temp failure failed for the wrong reason'
        fi
        grep -Fxq 'initial retirement attempt temp failure injected' \
            "$WORK/retirement-attempt-temp-fault.log" || \
            record_retirement_failure 'initial attempt temp failure injection was not reached'
        [ "$(legacy_login_state)" = t ] || record_retirement_failure \
            'initial attempt temp failure changed legacy LOGIN state'
        if [ -e "$EVIDENCE/legacy-retirement" ] || [ -L "$EVIDENCE/legacy-retirement" ]; then
            record_retirement_failure \
                'initial attempt temp failure left stale authoritative retirement success claimable'
        fi
        ! grep -q 'legacy retirement complete' "$WORK/retirement-attempt-temp-failure.out" || \
            record_retirement_failure 'initial attempt temp failure claimed retirement success'

        RETIREMENT_SOAK_FILE=
        assert_retirement_refused missing-soak 'accepted-soak evidence is required'

        RETIREMENT_SOAK_FILE="$SOAK_DIR/accepted"
        printf '%s\n' 'accepted_soak=PASS' 'malformed=true' >"$RETIREMENT_SOAK_FILE"
        chmod 600 "$RETIREMENT_SOAK_FILE"
        assert_retirement_refused malformed-soak 'accepted-soak evidence is malformed'

        write_soak_marker PASS "$HEAD" "$retirement_target_fingerprint" \
            "$((retirement_now - 86401))"
        assert_retirement_refused stale-soak 'accepted-soak evidence is stale'

        write_soak_marker PASS "$HEAD" "$retirement_target_fingerprint" "$retirement_now"
        mv "$RETIREMENT_SOAK_FILE" "$SOAK_DIR/accepted-target"
        make_unsafe_link "$SOAK_DIR/accepted-target" "$RETIREMENT_SOAK_FILE"
        assert_unsafe_link_platform "$RETIREMENT_SOAK_FILE"
        assert_retirement_refused unsafe-soak 'accepted-soak evidence file is invalid'
        rm -f "$RETIREMENT_SOAK_FILE" "$SOAK_DIR/accepted-target"

        write_soak_marker FAIL "$HEAD" "$retirement_target_fingerprint" "$retirement_now"
        assert_retirement_refused unaccepted-soak 'accepted soak is not PASS'

        write_soak_marker PASS "$HEAD" \
            0000000000000000000000000000000000000000000000000000000000000000 \
            "$retirement_now"
        assert_retirement_refused inconsistent-soak 'accepted-soak target fingerprint mismatch'

        write_soak_marker PASS "$HEAD" "$retirement_target_fingerprint" "$retirement_now"
        mv "$EVIDENCE/after-plan-validation.tsv" "$WORK/after-plan-validation.tsv"
        assert_retirement_refused missing-prerequisite 'required adoption evidence file is invalid'
        mv "$WORK/after-plan-validation.tsv" "$EVIDENCE/after-plan-validation.tsv"

        mv "$EVIDENCE/after-plan-validation.tsv" "$WORK/after-plan-validation.tsv"
        make_unsafe_link "$WORK/after-plan-validation.tsv" "$EVIDENCE/after-plan-validation.tsv"
        assert_retirement_refused unsafe-prerequisite 'required adoption evidence file is invalid'
        rm -f "$EVIDENCE/after-plan-validation.tsv"
        mv "$WORK/after-plan-validation.tsv" "$EVIDENCE/after-plan-validation.tsv"

        cat >"$WORK/unsafe-retirement-target" <<EOF
exact_commit=$HEAD
stage=legacy_retired
target_fingerprint=$retirement_target_fingerprint
post_retirement_fingerprint=$retirement_target_fingerprint
legacy_credential_retired=PASS
privilege_contract_result=PASS
environment_isolation_result=PASS
accepted_soak=PASS
EOF
        chmod 600 "$WORK/unsafe-retirement-target"
        make_unsafe_link "$WORK/unsafe-retirement-target" "$EVIDENCE/legacy-retirement"
        assert_unsafe_link_platform "$EVIDENCE/legacy-retirement"
        if RETIREMENT_FAILPOINT=alteration run_retirement --retire-legacy \
            >"$WORK/retirement-unsafe-destination.out" 2>&1; then
            record_retirement_failure 'unsafe retirement destination unexpectedly succeeded'
        elif ! grep -q 'legacy retirement evidence file is invalid' \
            "$WORK/retirement-unsafe-destination.out"; then
            record_retirement_failure 'unsafe retirement destination failed for the wrong reason'
        fi
        [ "$(legacy_login_state)" = t ] || record_retirement_failure \
            'unsafe retirement destination reached legacy role alteration'
        if validate_protected_evidence_file "$EVIDENCE/legacy-retirement" \
            'unsafe retirement destination' >/dev/null 2>&1; then
            record_retirement_failure 'unsafe retirement destination remained trusted'
        fi
        rm -f "$EVIDENCE/legacy-retirement" "$WORK/unsafe-retirement-target"

        assert_retirement_failure alteration-failure alteration \
            'legacy role alteration failed' t
        assert_retirement_failure verification-failure verification \
            'post-retirement verification failed' f
        reset_legacy_login
        rm -f "$WORK/retirement-publish-temp-fault.log"
        assert_retirement_failure publication-failure publication \
            'retirement evidence publication failed' f
        reset_legacy_login

        : >"$WORK/retirement-gates.log"
        seed_stale_retirement_success
        if ! run_retirement --retire-legacy >"$WORK/retirement-valid.out" 2>&1; then
            record_retirement_failure 'valid explicit retirement remained unimplemented'
            sed -n '1,180p' "$WORK/retirement-valid.out" >&2 || true
        else
            [ "$(legacy_login_state)" = f ] || \
                record_retirement_failure 'valid retirement did not set legacy NOLOGIN'
            cmp -s "$EVIDENCE/committed.tsv" "$EVIDENCE/retirement-after.tsv" || \
                record_retirement_failure 'retirement changed the canonical owner/ACL manifest'
            cat >"$WORK/expected-retirement-gates" <<'EOF'
privilege_contracts
environment_isolation
EOF
            cmp -s "$WORK/expected-retirement-gates" "$WORK/retirement-gates.log" || \
                record_retirement_failure 'post-retirement gates did not pass in frozen order'
            for field in \
                'stage=legacy_retired' \
                "exact_commit=$HEAD" \
                "target_fingerprint=$retirement_target_fingerprint" \
                "post_retirement_fingerprint=$retirement_target_fingerprint" \
                'legacy_credential_retired=PASS' \
                'privilege_contract_result=PASS' \
                'environment_isolation_result=PASS' \
                'accepted_soak=PASS'; do
                grep -Fxq "$field" "$EVIDENCE/legacy-retirement" || \
                    record_retirement_failure "retirement evidence lacks $field"
            done
            [ ! -L "$EVIDENCE/legacy-retirement" ] || \
                record_retirement_failure 'retirement evidence retained a symlink'
            [ "$(stat -c '%a' "$EVIDENCE/legacy-retirement")" = 600 ] || \
                record_retirement_failure 'retirement evidence is not mode 0600'
            [ "$(stat -c '%a' "$EVIDENCE")" = 700 ] || \
                record_retirement_failure 'retirement evidence directory is not mode 0700'
            ! grep -E 'ci-only|postgresql://|DATABASE_URL|PASSWORD' \
                "$EVIDENCE/legacy-retirement" || \
                record_retirement_failure 'retirement evidence contains credential material'
        fi

        [ "$retirement_failures" -eq 0 ] || {
            echo "$retirement_failures retirement assertion(s) failed" >&2
            exit 1
        }
        echo 'postgres adoption legacy retirement integration: PASS'
    fi

    echo 'postgres adoption success integration: PASS'
else
    echo 'postgres adoption before_commit integration: PASS'
fi
