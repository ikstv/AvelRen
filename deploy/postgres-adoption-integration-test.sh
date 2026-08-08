#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT=$(cd "$(dirname "$0")/.." && pwd)
readonly ROOT

[ "${AVELREN_ADOPTION_SCENARIO:-}" = before_commit ] || {
    echo 'Task 6 integration supports only AVELREN_ADOPTION_SCENARIO=before_commit' >&2
    exit 2
}

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
services:
  db:
    image: timescale/timescaledb:2.17.2-pg16
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: ci-only
      POSTGRES_DB: postgres
      AVELREN_COMPOSE_ENV_GUARD: \${AVELREN_COMPOSE_ENV_GUARD:?missing disposable Compose env guard}
    volumes:
      - '$ROOT_FOR_COMPOSE:/workspace:ro'
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d postgres"]
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
EOF

readonly TARGET_DB=avelren_adoption_test
readonly ADMIN_PASSWORD=ci-only
readonly ADMIN_DSN="postgresql://avelren_admin:ci-only@localhost:5432/$TARGET_DB"
readonly BOOTSTRAP_DSN='postgresql://avelren_admin:ci-only@localhost:5432/postgres'
readonly MIGRATOR_DSN="postgresql://avelren_migrator:ci-only@db:5432/$TARGET_DB"

real_compose up --detach --wait db
for _ in $(seq 1 30); do
    if PGPASSWORD="$ADMIN_PASSWORD" real_compose exec -T -e PGPASSWORD db \
        psql -U postgres -d postgres -At -c 'SELECT 1;' >/dev/null 2>&1; then
        break
    fi
    sleep 1
done
PGPASSWORD="$ADMIN_PASSWORD" real_compose exec -T -e PGPASSWORD db \
    psql -U postgres -d postgres -v ON_ERROR_STOP=1 -q \
    -c 'DROP EXTENSION IF EXISTS timescaledb;' \
    -c "CREATE ROLE avelren_admin LOGIN SUPERUSER PASSWORD 'ci-only';"
PGPASSWORD="$ADMIN_PASSWORD" real_compose exec -T -e PGPASSWORD db \
    psql -U postgres -d template1 -v ON_ERROR_STOP=1 -q \
    -c 'DROP EXTENSION IF EXISTS timescaledb;'
AVELREN_ADMIN_DSN="$BOOTSTRAP_DSN" AVELREN_ADMIN_PASSWORD="$ADMIN_PASSWORD" \
AVELREN_MIGRATOR_PASSWORD=ci-only AVELREN_BACKUP_PASSWORD=ci-only \
AVELREN_COLLECTOR_PASSWORD=ci-only AVELREN_NOTIFIER_PASSWORD=ci-only \
AVELREN_WATCHDOG_PASSWORD=ci-only AVELREN_API_PASSWORD=ci-only \
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
CREATE DATABASE avelren_residual_test OWNER postgres;
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
MSYS_NO_PATHCONV=1 "$ADOPTION_REAL_DOCKER" compose \
    --project-directory "$ADOPTION_PROJECT_DIR" --env-file "$ADOPTION_ENV_FILE" \
    -p "$ADOPTION_PROJECT" -f "$ADOPTION_COMPOSE_FILE" \
    exec -T -e PGPASSWORD=ci-only db \
    psql -U avelren_admin -d avelren_adoption_test "$@"
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
    *' stop caddy api collector notifier watchdog '*) printf '%s\n' stopped >"$ADOPTION_SERVICE_STATE" ;;
    *' stop '*) printf '%s\n' stopped >"$ADOPTION_SERVICE_STATE" ;;
    *' up '*) echo 'unexpected optimistic restart' >&2; exit 91 ;;
esac
SH
chmod +x "$BIN/psql" "$BIN/docker"
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
        _target_ownership_sql
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
        _target_ownership_sql
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
    "$WORK/residual-non-public-relation.sql" 'residual legacy ownership detected'

cat >"$WORK/residual-routine.sql" <<'SQL'
CREATE SCHEMA residual_test AUTHORIZATION avelren_admin;
CREATE FUNCTION residual_test.unexpected_function() RETURNS integer
    LANGUAGE sql AS 'SELECT 1';
ALTER FUNCTION residual_test.unexpected_function() OWNER TO avelren;
SQL
assert_target_check_rejects residual-routine "$WORK/residual-routine.sql" \
    'residual legacy ownership detected'

cat >"$WORK/residual-type.sql" <<'SQL'
CREATE SCHEMA residual_test AUTHORIZATION avelren_admin;
CREATE TYPE residual_test.unexpected_type AS ENUM ('unexpected');
ALTER TYPE residual_test.unexpected_type OWNER TO avelren;
SQL
assert_target_check_rejects residual-type "$WORK/residual-type.sql" \
    'residual legacy ownership detected'

cat >"$WORK/residual-timescale.sql" <<'SQL'
CREATE TABLE _timescaledb_internal.unexpected_relation(id integer);
ALTER TABLE _timescaledb_internal.unexpected_relation OWNER TO avelren;
SQL
assert_target_check_rejects residual-timescale "$WORK/residual-timescale.sql" \
    'residual legacy ownership detected'

cat >"$WORK/residual-shared.sql" <<'SQL'
ALTER DATABASE avelren_residual_test OWNER TO avelren;
SQL
assert_target_check_rejects residual-shared "$WORK/residual-shared.sql" \
    'residual legacy ownership detected'

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
        AVELREN_STACK_DIR="$ROOT" AVELREN_TARGET_DB="$TARGET_DB" \
        AVELREN_ADMIN_DSN="$ADMIN_DSN" AVELREN_EXPECTED_COMMIT="$HEAD" \
        AVELREN_RECOVERY_PREFLIGHT_FILE="$PREFLIGHT" AVELREN_EVIDENCE_DIR="$EVIDENCE" \
        AVELREN_TEST_DB=1 AVELREN_ALLOW_DIRTY_TEST=1 AVELREN_ADOPTION_FAILPOINT=before_commit \
        bash "$ROOT/deploy/postgres-adopt.sh" --confirm-adoption AVELREN-POSTGRES-ADOPTION
}

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

echo 'postgres adoption before_commit integration: PASS'
