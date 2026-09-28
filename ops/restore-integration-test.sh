#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT=$(cd "$(dirname "$0")/.." && pwd)
readonly ROOT
ROOT_FOR_COMPOSE=$ROOT
if command -v cygpath >/dev/null 2>&1; then
    ROOT_FOR_COMPOSE=$(cygpath -w "$ROOT")
fi
readonly ROOT_FOR_COMPOSE

PROJECT="avelren-restore-${RANDOM}-${RANDOM}"
COMPOSE_FILE_POSIX=$(mktemp)
COMPOSE_PROJECT_DIR_POSIX=$(mktemp -d)
COMPOSE_ENV_FILE_POSIX="$COMPOSE_PROJECT_DIR_POSIX/compose.env"
WORK=$(mktemp -d)
BLOCKER_PID=
readonly PROJECT COMPOSE_FILE_POSIX COMPOSE_PROJECT_DIR_POSIX COMPOSE_ENV_FILE_POSIX WORK

WORK_FOR_COMPOSE=$WORK
if command -v cygpath >/dev/null 2>&1; then
    WORK_FOR_COMPOSE=$(cygpath -w "$WORK")
fi
readonly WORK_FOR_COMPOSE

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

compose() {
    MSYS_NO_PATHCONV=1 docker compose \
        --project-directory "$COMPOSE_PROJECT_DIR" \
        --env-file "$COMPOSE_ENV_FILE" \
        -p "$PROJECT" -f "$COMPOSE_FILE" "$@"
}

require_log_text() {
    local pattern=${1:?pattern is required}
    local file=${2:?log file is required}
    grep -q -- "$pattern" "$file" || {
        echo "restore integration failed: expected log text not found: $pattern" >&2
        cat "$file" >&2
        return 1
    }
}

cleanup() {
    local status=$?
    trap - EXIT
    [ -z "$BLOCKER_PID" ] || { kill "$BLOCKER_PID" >/dev/null 2>&1 || true; wait "$BLOCKER_PID" 2>/dev/null || true; }
    compose down --volumes --remove-orphans >/dev/null 2>&1 || true
    rm -f "$COMPOSE_FILE_POSIX"
    rm -rf "$COMPOSE_PROJECT_DIR_POSIX" "$WORK"
    exit "$status"
}
trap cleanup EXIT

cat >"$COMPOSE_FILE_POSIX" <<EOF
services:
  db:
    image: timescale/timescaledb:2.17.2-pg16@sha256:4e459e217f00cbb09920c34d245501e63427e6767a495de57ce76823ff280f12
    environment:
      POSTGRES_USER: avelren_admin
      POSTGRES_PASSWORD: ci-only
      POSTGRES_DB: postgres
      AVELREN_COMPOSE_ENV_GUARD: \${AVELREN_COMPOSE_ENV_GUARD:?missing disposable Compose env guard}
    volumes:
      - '$ROOT_FOR_COMPOSE:/workspace:ro'
    healthcheck:
      # -h 127.0.0.1 forces the probe onto TCP, the transport the clients use
      # (#146). Without it pg_isready falls back to the unix socket and answers
      # for the temporary server initdb runs during first-time setup, which
      # listens on the socket only. The container then reports Healthy while the
      # real server has not started accepting TCP, and the first psql loses the
      # race. Measured in run 33898304081: Healthy at 17:03:12.0, connection
      # refused at 17:03:12.2. The other disposable suites already probe on TCP.
      test: ["CMD-SHELL", "pg_isready -h 127.0.0.1 -U avelren_admin -d postgres"]
      interval: 2s
      timeout: 2s
      retries: 30
  test:
    # The private evidence directory belongs to the invoking test user.
    # Root without DAC_OVERRIDE cannot write a different user's mode-0700 dir.
    user: "$(id -u):$(id -g)"
    cap_drop: [ALL]
    security_opt: ["no-new-privileges:true"]
    build:
      context: '$ROOT_FOR_COMPOSE'
      dockerfile: ops/Dockerfile.database-test
    environment:
      AVELREN_TEST_DB: "1"
      PYTHONPATH: /workspace/services/backend/src
      DATABASE_URL: postgresql://avelren_migrator:ci-only@db:5432/restore_test
    volumes:
      - '$ROOT_FOR_COMPOSE:/workspace:ro'
      - '$WORK_FOR_COMPOSE:/evidence'
    working_dir: /workspace
    networks: [default]
    depends_on:
      db:
        condition: service_healthy
EOF

readonly ADMIN_PASSWORD=ci-only
readonly BACKUP_PASSWORD=ci-only
readonly MIGRATOR_PASSWORD=ci-only
readonly SOURCE_DB=avelren_restore_source_test
readonly TARGET_DB=restore_test
readonly MARKER=restore-integration-marker-v2
readonly DUMP="$WORK/source.sql.gz"
readonly SIDECAR="$DUMP.sha256"
readonly EVIDENCE="$WORK/recovery-evidence.json"
readonly UNEXPECTED_DUMP="$WORK/source-unexpected.sql.gz"
readonly MISSING_DUMP="$WORK/source-missing.sql.gz"
readonly BOOTSTRAP_DSN='postgresql://avelren_admin:ci-only@localhost:5432/postgres'
readonly MIGRATOR_SOURCE_DSN="postgresql://avelren_migrator:ci-only@db:5432/$SOURCE_DB"
readonly API_SOURCE_DSN="postgresql://avelren_api:ci-only@db:5432/$SOURCE_DB"
readonly MIGRATOR_TARGET_DSN="postgresql://avelren_migrator:ci-only@db:5432/$TARGET_DB"
readonly API_TARGET_DSN="postgresql://avelren_api:ci-only@db:5432/$TARGET_DB"

run_restore() {
    local dump=$1
    AVELREN_COMPOSE_PROJECT_DIR="$COMPOSE_PROJECT_DIR" \
    AVELREN_COMPOSE_ENV_FILE="$COMPOSE_ENV_FILE" \
    AVELREN_ADMIN_PASSWORD="$ADMIN_PASSWORD" \
    bash -c 'set -euo pipefail; source "$1"; _avelren_restore_engine_primitive "$2" "$3" "$4" "$5" "$6" db' \
      bash "$ROOT/ops/restore-engine.lib.sh" "$dump" "$TARGET_DB" "$ROOT" "$COMPOSE_FILE" "$PROJECT"
}

[ "$PROJECT" != avelren ]
[ "$TARGET_DB" != avelren ]
[ "$COMPOSE_PROJECT_DIR_POSIX" != /opt/avelren ]
compose up --detach --wait db
if docker ps -a --filter "label=com.docker.compose.project=$PROJECT" --format '{{.Names}}' | \
   grep -qx 'avelren-db-1'; then
    echo 'restore integration used the canonical production container name' >&2; exit 1
fi
if docker network ls --filter "label=com.docker.compose.project=$PROJECT" --format '{{.Name}}' | \
   grep -qx 'avelren_default'; then
    echo 'restore integration used the canonical production network name' >&2; exit 1
fi
if docker volume ls --filter "label=com.docker.compose.project=$PROJECT" --format '{{.Name}}' | \
   grep -qx 'avelren_db_data'; then
    echo 'restore integration used the canonical production volume name' >&2; exit 1
fi
# The expression is evaluated inside the database container.
# shellcheck disable=SC2016
compose exec -T db sh -c '[ "$AVELREN_COMPOSE_ENV_GUARD" = isolated ]'

AVELREN_ADMIN_DSN="$BOOTSTRAP_DSN" \
AVELREN_ADMIN_PASSWORD="$ADMIN_PASSWORD" \
AVELREN_MIGRATOR_PASSWORD="$MIGRATOR_PASSWORD" \
AVELREN_BACKUP_PASSWORD="$BACKUP_PASSWORD" \
AVELREN_COLLECTOR_PASSWORD=ci-only \
AVELREN_NOTIFIER_PASSWORD=ci-only \
AVELREN_WATCHDOG_PASSWORD=ci-only \
AVELREN_API_PASSWORD=ci-only \
compose exec -T \
    -e AVELREN_TEST_DB -e AVELREN_DB_NAME \
    -e AVELREN_ADMIN_DSN -e AVELREN_ADMIN_PASSWORD \
    -e AVELREN_MIGRATOR_PASSWORD -e AVELREN_BACKUP_PASSWORD \
    -e AVELREN_COLLECTOR_PASSWORD -e AVELREN_NOTIFIER_PASSWORD \
    -e AVELREN_WATCHDOG_PASSWORD -e AVELREN_API_PASSWORD \
    -e AVELREN_DB_NAME="$SOURCE_DB" -e AVELREN_TEST_DB=1 \
    db bash /workspace/ops/postgres-bootstrap.sh fresh

compose run --rm --no-deps -T test python ops/verify-python-container-security.py
DATABASE_URL="$MIGRATOR_SOURCE_DSN" compose run --rm --no-deps -T \
    -e DATABASE_URL test python -m avelren.migrate db/migrations

PGPASSWORD="$ADMIN_PASSWORD" compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$SOURCE_DB" -v ON_ERROR_STOP=1 -q \
    -c "INSERT INTO checkpoints
        (id, title, for_vehicle_type, first_seen, last_seen)
        VALUES (987654320, '$MARKER', 1, now(), now());" \
    -c "INSERT INTO observations
        (time, checkpoint_id, wait_time_seconds, vehicles_in_queue, is_paused)
        VALUES (now(), 987654320, 60, 1, false);" \
    -c "CREATE TABLE public.unexpected_relation (marker text NOT NULL);" \
    -c "INSERT INTO public.unexpected_relation VALUES ('must-remain-admin-owned');" \
    -c "GRANT SELECT ON public.unexpected_relation TO avelren_backup;"

if PGPASSWORD="$BACKUP_PASSWORD" compose exec -T -e PGPASSWORD db \
    psql -U avelren_backup -d "$SOURCE_DB" -v ON_ERROR_STOP=1 -q \
    -c "INSERT INTO checkpoints
        (id, title, for_vehicle_type, first_seen, last_seen)
        VALUES (987654319, 'backup-must-not-write', 1, now(), now());" \
    >"$WORK/backup-write.out" 2>&1; then
    echo 'restore integration failed: backup role inserted a marker' >&2
    exit 1
fi

PGPASSWORD="$BACKUP_PASSWORD" compose exec -T -e PGPASSWORD db \
    pg_dump --no-owner -U avelren_backup -d "$SOURCE_DB" | gzip -9 >"$UNEXPECTED_DUMP"
if run_restore "$UNEXPECTED_DUMP" >"$WORK/unexpected-restore.out" 2>&1; then
    echo 'restore integration failed: unexpected application relation passed ownership preflight' >&2
    exit 1
fi
require_log_text 'restore application relation allowlist mismatch' "$WORK/unexpected-restore.out"
unexpected_state=$(PGPASSWORD="$ADMIN_PASSWORD" compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$TARGET_DB" -At \
    -c "SELECT relation.relname || ':' || owner.rolname || ':' ||
               (SELECT marker FROM public.unexpected_relation LIMIT 1)
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        JOIN pg_roles AS owner ON owner.oid = relation.relowner
        WHERE namespace.nspname = 'public'
          AND relation.relname = 'unexpected_relation';")
[ "$unexpected_state" = 'unexpected_relation:avelren_admin:must-remain-admin-owned' ]
canonical_owner_after_unexpected=$(PGPASSWORD="$ADMIN_PASSWORD" compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$TARGET_DB" -At \
    -c "SELECT tableowner FROM pg_tables
        WHERE schemaname = 'public' AND tablename = 'schema_migrations';")
[ "$canonical_owner_after_unexpected" = avelren_admin ] || {
    echo 'restore integration failed: ownership mutation began before unexpected-relation rejection' >&2
    exit 1
}

PGPASSWORD="$ADMIN_PASSWORD" compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$SOURCE_DB" -v ON_ERROR_STOP=1 -q \
    -c 'DROP TABLE public.unexpected_relation;'

PGPASSWORD="$BACKUP_PASSWORD" compose exec -T -e PGPASSWORD db \
    pg_dump --no-owner -U avelren_backup -d "$SOURCE_DB" | gzip -9 >"$DUMP"

dump_digest=$(sha256sum "$DUMP" | awk '{print $1}')
printf '%s  %s\n' "$dump_digest" "$(basename "$DUMP")" >"$SIDECAR"
target_commit=$(git -C "$ROOT" rev-parse HEAD)
compose run --rm --no-deps -T test python - \
  /evidence/recovery-evidence.json /workspace "$target_commit" "$dump_digest" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

output, root, target_commit, dump_sha = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4]
files = sorted((root / "db" / "migrations").glob("[0-9][0-9][0-9]_*.sql"))
roles = {
    "avelren_admin": {"login": True, "superuser": True},
    "avelren_migrator": {"login": True, "superuser": False},
    "avelren_backup": {"login": True, "superuser": False},
    "avelren_collector": {"login": True, "superuser": False},
    "avelren_notifier": {"login": True, "superuser": False},
    "avelren_watchdog": {"login": True, "superuser": False},
    "avelren_api": {"login": True, "superuser": False},
}
output.write_text(json.dumps({
    "target_commit": target_commit,
    "recovery_migration_pin": files[-1].stem,
    "database_journal": {path.stem: hashlib.sha256(path.read_bytes()).hexdigest() for path in files},
    "role_model": "least-privilege-v1",
    "roles": roles,
    "role_memberships": {role: [] for role in roles},
    "ownership_and_grants_verified": True,
    "backup_sha256": dump_sha,
}), encoding="utf-8")
PY
bash -c 'source "$1"; avelren_verify_restore_artifact "$2" "$3"' \
  bash "$ROOT/ops/restore-artifact.lib.sh" "$DUMP" "$SIDECAR"
compose run --rm --no-deps -T test python /workspace/ops/restore-role-pin.py verify \
  --record /evidence/recovery-evidence.json --source-root /workspace --dump-sha256 "$dump_digest"

run_restore "$DUMP"

restored=$(PGPASSWORD="$ADMIN_PASSWORD" compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$TARGET_DB" -At \
    -c 'SELECT title FROM checkpoints WHERE id = 987654320;')
[ "$restored" = "$MARKER" ] || {
    echo 'restore integration failed: deterministic marker missing' >&2
    exit 1
}
restored_owner=$(PGPASSWORD="$ADMIN_PASSWORD" compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$TARGET_DB" -At \
    -c "SELECT tableowner FROM pg_tables WHERE schemaname = 'public' AND tablename = 'schema_migrations';")
[ "$restored_owner" = avelren_migrator ] || {
    echo 'restore integration failed: application ownership was not restored to migrator' >&2
    exit 1
}

# A live, otherwise valid client session must make the post-stop quiescence
# predicate false. This session belongs only to the random disposable project.
PGPASSWORD="$ADMIN_PASSWORD" compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$TARGET_DB" -v ON_ERROR_STOP=1 \
    -c "SET application_name='restore-integration-blocker'; SELECT pg_sleep(30);" \
    >"$WORK/blocker.out" 2>&1 &
BLOCKER_PID=$!
for _ in $(seq 1 20); do
    blocker_seen=$(PGPASSWORD="$ADMIN_PASSWORD" compose exec -T -e PGPASSWORD db \
        psql -U avelren_admin -d "$TARGET_DB" -At \
        -c "SELECT EXISTS (SELECT 1 FROM pg_stat_activity WHERE application_name='restore-integration-blocker');")
    [ "$blocker_seen" != t ] || break
    sleep 1
done
[ "$blocker_seen" = t ]
quiescent=$(PGPASSWORD="$ADMIN_PASSWORD" compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$TARGET_DB" -At \
    -c "SELECT NOT EXISTS (
          SELECT 1 FROM pg_stat_activity
          WHERE datname=current_database() AND pid<>pg_backend_pid()
            AND backend_type='client backend');")
[ "$quiescent" = f ] || {
    echo 'restore integration failed: active session was not refused' >&2; exit 1; }
PGPASSWORD="$ADMIN_PASSWORD" compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$TARGET_DB" -v ON_ERROR_STOP=1 -At \
    -c "SELECT pg_terminate_backend(pid)
        FROM pg_stat_activity
        WHERE application_name='restore-integration-blocker';" \
    | grep -qx t
kill "$BLOCKER_PID" >/dev/null 2>&1 || true
wait "$BLOCKER_PID" 2>/dev/null || true
BLOCKER_PID=

PGPASSWORD="$ADMIN_PASSWORD" compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$SOURCE_DB" -v ON_ERROR_STOP=1 -q \
    -c 'DROP TABLE public.notification_cancels;'
PGPASSWORD="$BACKUP_PASSWORD" compose exec -T -e PGPASSWORD db \
    pg_dump --no-owner -U avelren_backup -d "$SOURCE_DB" | gzip -9 >"$MISSING_DUMP"
if run_restore "$MISSING_DUMP" >"$WORK/missing-restore.out" 2>&1; then
    echo 'restore integration failed: missing expected relation passed ownership preflight' >&2
    exit 1
fi
require_log_text 'restore application relation allowlist mismatch' "$WORK/missing-restore.out"
missing_owner_state=$(PGPASSWORD="$ADMIN_PASSWORD" compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$TARGET_DB" -At \
    -c "SELECT tableowner FROM pg_tables
        WHERE schemaname = 'public' AND tablename = 'schema_migrations';")
[ "$missing_owner_state" = avelren_admin ] || {
    echo 'restore integration failed: ownership mutation began before missing-relation rejection' >&2
    exit 1
}
missing_relation=$(PGPASSWORD="$ADMIN_PASSWORD" compose exec -T -e PGPASSWORD db \
    psql -U avelren_admin -d "$TARGET_DB" -At \
    -c "SELECT to_regclass('public.notification_cancels') IS NULL;")
[ "$missing_relation" = t ]

# Restore the unchanged canonical dump once more after the fail-closed fixture.
run_restore "$DUMP"

if AVELREN_STACK_DIR="$ROOT" \
   AVELREN_COMPOSE_FILE="$COMPOSE_FILE" \
   AVELREN_COMPOSE_PROJECT="$PROJECT" \
   AVELREN_COMPOSE_PROJECT_DIR="$COMPOSE_PROJECT_DIR" \
   AVELREN_COMPOSE_ENV_FILE="$COMPOSE_ENV_FILE" \
   AVELREN_VERIFY_SCHEMA_SERVICE=test \
   AVELREN_VERIFY_API_SERVICE=test \
   AVELREN_VERIFY_MIGRATIONS_DIR=db/migrations \
   AVELREN_VERIFY_MIGRATOR_DSN="$MIGRATOR_SOURCE_DSN" \
   AVELREN_VERIFY_API_DSN="$API_SOURCE_DSN" \
   AVELREN_COMPOSE_ENV_GUARD=isolated \
   bash "$ROOT/ops/restore-verify.sh" "$TARGET_DB" \
       >"$WORK/wrong-target-verify.out" 2>&1; then
    echo 'restore integration failed: verification accepted credentials for the wrong database' >&2
    exit 1
fi

if AVELREN_STACK_DIR="$ROOT" \
   AVELREN_COMPOSE_FILE="$COMPOSE_FILE" \
   AVELREN_COMPOSE_PROJECT="$PROJECT" \
   AVELREN_COMPOSE_PROJECT_DIR="$COMPOSE_PROJECT_DIR" \
   AVELREN_COMPOSE_ENV_FILE="$COMPOSE_ENV_FILE" \
   AVELREN_VERIFY_SCHEMA_SERVICE=test \
   AVELREN_VERIFY_API_SERVICE=test \
   AVELREN_VERIFY_MIGRATIONS_DIR=db/migrations \
   AVELREN_VERIFY_MIGRATOR_DSN="$MIGRATOR_TARGET_DSN" \
   AVELREN_VERIFY_API_DSN="$MIGRATOR_TARGET_DSN" \
   AVELREN_COMPOSE_ENV_GUARD=isolated \
   bash "$ROOT/ops/restore-verify.sh" "$TARGET_DB" \
       >"$WORK/wrong-role-verify.out" 2>&1; then
    echo 'restore integration failed: API verification accepted the migrator role' >&2
    exit 1
fi

AVELREN_STACK_DIR="$ROOT" \
AVELREN_COMPOSE_FILE="$COMPOSE_FILE" \
AVELREN_COMPOSE_PROJECT="$PROJECT" \
AVELREN_COMPOSE_PROJECT_DIR="$COMPOSE_PROJECT_DIR" \
AVELREN_COMPOSE_ENV_FILE="$COMPOSE_ENV_FILE" \
AVELREN_VERIFY_SCHEMA_SERVICE=test \
AVELREN_VERIFY_API_SERVICE=test \
AVELREN_VERIFY_MIGRATIONS_DIR=db/migrations \
AVELREN_VERIFY_MIGRATOR_DSN="$MIGRATOR_TARGET_DSN" \
AVELREN_VERIFY_API_DSN="$API_TARGET_DSN" \
AVELREN_COMPOSE_ENV_GUARD=isolated \
bash "$ROOT/ops/restore-verify.sh" "$TARGET_DB"

echo "restore integration passed: backup=read-only dump, target=$TARGET_DB, least-privilege schema/smoke verified"

bad_dump="$WORK/fails-after-pre.sql.gz"
{
    printf 'THIS IS NOT VALID SQL;\n'
    head -c 20000 /dev/urandom | base64
} | gzip -c >"$bad_dump"
failure_log="$WORK/failure.log"
if AVELREN_STACK_DIR="$ROOT" \
   AVELREN_COMPOSE_FILE="$COMPOSE_FILE" \
   AVELREN_COMPOSE_PROJECT="$PROJECT" \
   AVELREN_COMPOSE_PROJECT_DIR="$COMPOSE_PROJECT_DIR" \
   AVELREN_COMPOSE_ENV_FILE="$COMPOSE_ENV_FILE" \
   AVELREN_DB_SERVICE=db \
   AVELREN_ADMIN_PASSWORD="$ADMIN_PASSWORD" \
   AVELREN_COMPOSE_ENV_GUARD=isolated \
   bash "$ROOT/ops/restore.sh" "$bad_dump" --target "$TARGET_DB" \
       >"$failure_log" 2>&1; then
    echo 'restore failure after pre_restore was expected' >&2
    exit 1
fi
require_log_text 'primary restore failure' "$failure_log"
require_log_text 'timescaledb_post_restore cleanup succeeded' "$failure_log"
echo 'restore failure cleanup passed: post_restore attempted, primary failure preserved'
