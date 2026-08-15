#!/usr/bin/env bash
# Integration test for the bootstrap-superuser adoption topology (Decision B).
#
# Unlike postgres-adoption-integration-test.sh (which bootstraps the cluster as a
# separate `clusteradmin` superuser and makes `avelren` a plain application
# owner), this suite initialises the disposable PostgreSQL cluster with
# POSTGRES_USER=avelren, so `avelren` is the REAL bootstrap superuser and owns
# the system catalogs (pg_catalog / information_schema / pg_toast), the database,
# the public schema, the timescaledb extension and all TimescaleDB internals —
# exactly the production topology proven read-only on the live host.
#
# It exercises the NEW code directly (postgres-ownership.lib.sh: manifest capture,
# forward/inverse plan builders, and the pg_class/pg_depend positive-allowlist
# verifier) against a real TimescaleDB, plus the TimescaleDB runtime behaviour
# under the post-adoption split ownership — including after the legacy `avelren`
# is set NOLOGIN. It never touches production and never invokes
# `postgres-adopt.sh --production-adopt`; the forward/inverse plans are applied
# in-transaction here so the verifier and round-trip are proven on real catalog
# state.
#
# HARD RULE: if a TimescaleDB runtime operation fails after `avelren -> NOLOGIN`,
# that is a signal to revisit Decision B — do NOT weaken the verifier.
set -euo pipefail
umask 077

ROOT=$(cd "$(dirname "$0")/.." && pwd)
readonly ROOT
# shellcheck source=deploy/postgres-ownership.lib.sh
source "$ROOT/deploy/postgres-ownership.lib.sh"

ROOT_FOR_COMPOSE=$ROOT
if command -v cygpath >/dev/null 2>&1; then
    ROOT_FOR_COMPOSE=$(cygpath -w "$ROOT")
fi
readonly ROOT_FOR_COMPOSE

PROJECT="avelren-bootstrap-${RANDOM}-${RANDOM}"
COMPOSE_FILE_POSIX=$(mktemp)
COMPOSE_PROJECT_DIR_POSIX=$(mktemp -d)
COMPOSE_ENV_FILE_POSIX="$COMPOSE_PROJECT_DIR_POSIX/compose.env"
WORK=$(mktemp -d)
readonly PROJECT COMPOSE_FILE_POSIX COMPOSE_PROJECT_DIR_POSIX COMPOSE_ENV_FILE_POSIX WORK

printf '%s\n' 'AVELREN_COMPOSE_ENV_GUARD=isolated' >"$COMPOSE_ENV_FILE_POSIX"

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

readonly TARGET_DB=avelren_bootstrap_test
readonly BOOTSTRAP_PW=bootstrap-ci-only
readonly ADMIN_PW=admin-ci-only
readonly MIGRATOR_PW=migrator-ci-only BACKUP_PW=backup-ci-only COLLECTOR_PW=collector-ci-only
readonly NOTIFIER_PW=notifier-ci-only WATCHDOG_PW=watchdog-ci-only API_PW=api-ci-only

# All DSNs use `db:5432` — resolved inside the compose network by the psql/test
# containers. `avelren` is both the bootstrap superuser and the legacy admin DSN.
readonly LEGACY_DSN="postgresql://avelren:${BOOTSTRAP_PW}@db:5432/${TARGET_DB}"
readonly ADMIN_TOOL_DSN="postgresql://avelren_admin:${ADMIN_PW}@db:5432/${TARGET_DB}"
readonly MIGRATOR_DSN="postgresql://avelren_migrator:${MIGRATOR_PW}@db:5432/${TARGET_DB}"
readonly BACKUP_DSN="postgresql://avelren_backup:${BACKUP_PW}@db:5432/${TARGET_DB}"
readonly COLLECTOR_DSN="postgresql://avelren_collector:${COLLECTOR_PW}@db:5432/${TARGET_DB}"
readonly NOTIFIER_DSN="postgresql://avelren_notifier:${NOTIFIER_PW}@db:5432/${TARGET_DB}"
readonly WATCHDOG_DSN="postgresql://avelren_watchdog:${WATCHDOG_PW}@db:5432/${TARGET_DB}"
readonly API_DSN="postgresql://avelren_api:${API_PW}@db:5432/${TARGET_DB}"

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

fail() { echo "bootstrap-topology adoption test FAILED: $*" >&2; exit 1; }

cat >"$COMPOSE_FILE_POSIX" <<EOF
services:
  db:
    image: timescale/timescaledb:2.17.2-pg16
    environment:
      # avelren IS the cluster bootstrap superuser here — this is the whole point.
      POSTGRES_USER: avelren
      POSTGRES_PASSWORD: ${BOOTSTRAP_PW}
      POSTGRES_DB: ${TARGET_DB}
      AVELREN_COMPOSE_ENV_GUARD: \${AVELREN_COMPOSE_ENV_GUARD:?missing disposable Compose env guard}
    volumes:
      - '${ROOT_FOR_COMPOSE}:/workspace:ro'
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -h 127.0.0.1 -U avelren -d ${TARGET_DB}"]
      interval: 2s
      timeout: 2s
      retries: 30
  test:
    build:
      context: '${ROOT_FOR_COMPOSE}'
      dockerfile: app/Dockerfile.test
    depends_on:
      db:
        condition: service_healthy
EOF

# ---- helpers: run psql inside the db container --------------------------------
# psql as the bootstrap/legacy avelren superuser (owns everything pre-adoption).
db_psql() {
    PGPASSWORD="$BOOTSTRAP_PW" real_compose exec -T -e PGPASSWORD db \
        psql -U avelren -d "$TARGET_DB" -v ON_ERROR_STOP=1 -qAt "$@"
}
db_psql_role() {
    local role=$1 pw=$2; shift 2
    PGPASSWORD="$pw" real_compose exec -T -e PGPASSWORD db \
        psql -U "$role" -d "$TARGET_DB" -v ON_ERROR_STOP=1 -qAt "$@"
}

# AVELREN_PSQL_BIN wrapper for ownership.lib's _adoption_psql: it sets
# PGDATABASE="<dsn>" then calls this. Real psql does not expand a URI from the
# PGDATABASE env var, so pass it as the positional conninfo inside the container.
cat >"$WORK/psql-wrapper.sh" <<WRAP
#!/usr/bin/env bash
exec "$REAL_DOCKER" compose --project-directory "$COMPOSE_PROJECT_DIR" \\
    --env-file "$COMPOSE_ENV_FILE" -p "$PROJECT" -f "$COMPOSE_FILE" \\
    exec -T -e PGDATABASE db sh -c 'exec psql "\$PGDATABASE" "\$@"' _ "\$@"
WRAP
chmod +x "$WORK/psql-wrapper.sh"
export AVELREN_PSQL_BIN="$WORK/psql-wrapper.sh"
export AVELREN_TARGET_DB="$TARGET_DB"

# ---- 0. boot -----------------------------------------------------------------
echo '>>> booting bootstrap-avelren PostgreSQL'
real_compose up --detach --wait db
ready=0
for _ in $(seq 1 30); do
    if db_psql -c 'SELECT 1;' >/dev/null 2>&1; then ready=1; break; fi
    sleep 1
done
[ "$ready" -eq 1 ] || { real_compose logs --no-color db >&2 || true; fail 'db not ready'; }

# ---- 1. pre-adoption topology + setup ----------------------------------------
echo '>>> setup: timescaledb + roles + migrations + seed + chunk + continuous aggregate'
# avelren (bootstrap) owns the extension.
db_psql -c 'CREATE EXTENSION IF NOT EXISTS timescaledb;' >/dev/null

# Provision the 7 least-privilege roles (bootstrap.sql, run as avelren superuser).
db_psql \
    --set=avelren_admin_password="$ADMIN_PW" \
    --set=avelren_migrator_password="$MIGRATOR_PW" \
    --set=avelren_backup_password="$BACKUP_PW" \
    --set=avelren_collector_password="$COLLECTOR_PW" \
    --set=avelren_notifier_password="$NOTIFIER_PW" \
    --set=avelren_watchdog_password="$WATCHDOG_PW" \
    --set=avelren_api_password="$API_PW" \
    -f /workspace/db/security/bootstrap.sql >/dev/null

# Apply migrations 001-009 AS avelren, so application objects are owned by the
# bootstrap legacy role (the real pre-adoption state).
MIGR="$WORK/migr"; mkdir -p "$MIGR"; cp "$ROOT"/db/migrations/00[1-9]_*.sql "$MIGR/"
MIGR_FC=$MIGR; command -v cygpath >/dev/null 2>&1 && MIGR_FC=$(cygpath -w "$MIGR")
DATABASE_URL="$LEGACY_DSN" real_compose run --rm --no-deps -T \
    -v "$MIGR_FC:/prefix-migrations:ro" -e DATABASE_URL \
    test python -m avelren.migrate /prefix-migrations >/dev/null

# Pin the chunk interval (see the sibling suite's note) and seed one real chunk +
# refresh the continuous aggregate so the cagg has materialised internals.
db_psql <<'SQL' >/dev/null
SELECT set_chunk_time_interval('public.observations', INTERVAL '36500 days');
INSERT INTO public.checkpoints (id, title, for_vehicle_type) VALUES (-1, 'bootstrap fixture', 1);
INSERT INTO public.observations (time, checkpoint_id, wait_time_seconds, vehicles_in_queue, is_paused)
VALUES (now(), -1, 60, 1, false);
CALL refresh_continuous_aggregate('public.observations_hourly', NULL, NULL);
SQL

# ---- 2. pre-adoption assertions ----------------------------------------------
echo '>>> pre-adoption assertions'
[ "$(db_psql -c "SELECT rolsuper::text||','||rolcanlogin::text FROM pg_roles WHERE rolname='avelren'")" = 'true,true' ] \
    || fail 'avelren is not SUPERUSER+LOGIN pre-adoption'
# avelren owns the system catalogs (bootstrap) — this is what the manifest
# scoping must exclude from the application surface.
sys_owned=$(db_psql -c "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('pg_catalog','information_schema') AND c.relowner=(SELECT oid FROM pg_roles WHERE rolname='avelren')")
[ "${sys_owned:-0}" -gt 0 ] || fail 'avelren does not own system catalogs — not a bootstrap topology'
# All 20 canonical relations owned by avelren.
canon_avelren=$(db_psql -c "SELECT count(*) FROM (SELECT unnest(ARRAY['alerts','alerts_id_seq','checkpoints','collector_runs','countries','devices','eta_alerts','eta_alerts_id_seq','eta_targets','eta_targets_id_seq','health_alerts','health_alerts_id_seq','notification_cancels','notification_cancels_id_seq','observations','observations_hourly','schema_migrations','subscription_state','subscriptions','subscriptions_id_seq']) AS nm) c JOIN pg_class r ON r.relname=c.nm JOIN pg_namespace n ON n.oid=r.relnamespace AND n.nspname='public' WHERE pg_get_userbyid(r.relowner)='avelren'")
[ "$canon_avelren" = 20 ] || fail "expected 20 canonical relations owned by avelren, got $canon_avelren"

# The proven closure invariant (closure=78, closure ∩ protected=0), read-only.
CLOSURE_SQL=$(cat <<'SQL'
CREATE TEMP TABLE _canon(name text) ON COMMIT DROP;
INSERT INTO _canon VALUES ('alerts'),('alerts_id_seq'),('checkpoints'),('collector_runs'),('countries'),('devices'),('eta_alerts'),('eta_alerts_id_seq'),('eta_targets'),('eta_targets_id_seq'),('health_alerts'),('health_alerts_id_seq'),('notification_cancels'),('notification_cancels_id_seq'),('observations'),('observations_hourly'),('schema_migrations'),('subscription_state'),('subscriptions'),('subscriptions_id_seq');
CREATE TEMP TABLE _closure ON COMMIT DROP AS
WITH RECURSIVE seed AS (
  SELECT 'pg_class'::regclass::oid AS classid, c.oid AS objid
  FROM _canon JOIN pg_namespace n ON n.nspname='public'
  JOIN pg_class c ON c.relnamespace=n.oid AND c.relname=_canon.name),
closure(classid,objid) AS (
  SELECT classid,objid FROM seed
  UNION
  SELECT d.classid,d.objid FROM pg_depend d JOIN closure cl ON d.refclassid=cl.classid AND d.refobjid=cl.objid
  WHERE d.deptype IN ('i','a') AND d.classid IN ('pg_class'::regclass,'pg_type'::regclass))
SELECT DISTINCT classid,objid FROM closure;
CREATE TEMP TABLE _protected ON COMMIT DROP AS
  SELECT 'pg_class'::regclass::oid classid, c.oid objid FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname LIKE '%timescaledb%'
  UNION SELECT 'pg_type'::regclass::oid, t.oid FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname LIKE '%timescaledb%'
  UNION SELECT dep.classid, dep.objid FROM pg_depend dep JOIN pg_extension e ON e.oid=dep.refobjid AND e.extname='timescaledb' WHERE dep.refclassid='pg_extension'::regclass AND dep.deptype='e' AND dep.classid IN ('pg_class'::regclass,'pg_type'::regclass);
DO $v$
DECLARE inter bigint; toast_r bigint; idx bigint; seq bigint; comp bigint; chunks bigint;
BEGIN
  SELECT count(*) INTO inter FROM _closure c JOIN _protected p USING(classid,objid);
  IF inter <> 0 THEN RAISE EXCEPTION 'closure intersects protected surface (% objects)', inter; END IF;
  -- TOAST / index / sequence / composite present where expected.
  SELECT count(*) INTO toast_r FROM _closure z JOIN pg_class c ON c.oid=z.objid AND z.classid='pg_class'::regclass JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='pg_toast' AND c.relkind='t';
  SELECT count(*) INTO idx FROM _closure z JOIN pg_class c ON c.oid=z.objid AND z.classid='pg_class'::regclass WHERE c.relkind='i';
  SELECT count(*) INTO seq FROM _closure z JOIN pg_class c ON c.oid=z.objid AND z.classid='pg_class'::regclass WHERE c.relkind='S';
  SELECT count(*) INTO comp FROM _closure z JOIN pg_type t ON t.oid=z.objid AND z.classid='pg_type'::regclass WHERE t.typtype='c';
  IF toast_r = 0 THEN RAISE EXCEPTION 'closure has no TOAST tables (expected app-table toast)'; END IF;
  IF idx = 0 THEN RAISE EXCEPTION 'closure has no indexes'; END IF;
  IF seq <> 6 THEN RAISE EXCEPTION 'closure has % sequences, expected 6', seq; END IF;
  IF comp = 0 THEN RAISE EXCEPTION 'closure has no composite rowtypes'; END IF;
  -- Timescale chunks / cagg internals must be OUTSIDE the closure (protected).
  SELECT count(*) INTO chunks FROM _closure z JOIN pg_class c ON c.oid=z.objid AND z.classid='pg_class'::regclass JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname LIKE '%timescaledb%';
  IF chunks <> 0 THEN RAISE EXCEPTION 'closure captured % timescale-internal relations', chunks; END IF;
  RAISE NOTICE 'closure ok: no protected intersection; toast=%, idx=%, seq=%, composite=%', toast_r, idx, seq, comp;
END $v$;
SQL
)
# Wrap in one transaction so the ON COMMIT DROP temp tables survive across the
# statements (in psql autocommit each statement would otherwise commit + drop).
{ printf '%s\n' 'BEGIN;' "$CLOSURE_SQL" 'COMMIT;'; } | db_psql >/dev/null || fail 'pre-adoption closure invariant failed'
echo 'bootstrap-topology pre-adoption (topology + closure ∩ protected = 0): PASS'

# ---- 2.5 unexpected-database refusal (real catalog, pre-mutation) ------------
# Production regression 2026-08-14: a leftover disposable `restore_test` database
# owned by avelren_admin sat in the live cluster. Nothing refused it — the
# allowlist accepted a `shared` database with that owner — and plan generation
# then read BOTH database rows into the identity, emitting a broken
# `... ON DATABASE avelren\nrestore_test FROM ...`. Adoption failed on a SQL
# syntax error instead of a stated contract violation. Prove here, against a real
# catalog (fixtures cannot show that `database_inventory` actually captures the
# second database), that such a topology is refused BEFORE any mutation.
echo '>>> unexpected-database refusal'
REFUSE_EVID="$WORK/refuse"; mkdir -p "$REFUSE_EVID"; chmod 700 "$REFUSE_EVID"
prepare_evidence_dir "$REFUSE_EVID"
db_psql -c 'CREATE DATABASE avelren_leftover_test OWNER avelren_admin' >/dev/null \
    || fail 'could not create the leftover database fixture'
capture_manifest "$LEGACY_DSN" "$REFUSE_EVID/leftover.tsv"
grep -q $'\tdatabase\t.*\tavelren_leftover_test\t' "$REFUSE_EVID/leftover.tsv" \
    || fail 'capture did not record the leftover database — the scoping regression is not being exercised'
if validate_owned_object_allowlist "$REFUSE_EVID/leftover.tsv" >"$REFUSE_EVID/out" 2>&1; then
    db_psql -c 'DROP DATABASE avelren_leftover_test' >/dev/null || true
    fail 'an unexpected database owned by a canonical role must be refused'
fi
grep -q 'unexpected database owned by a canonical role: avelren_leftover_test' "$REFUSE_EVID/out" \
    || { db_psql -c 'DROP DATABASE avelren_leftover_test' >/dev/null || true
         fail 'refusal must name the offending database'; }
# Plan generation must refuse on BOTH paths, even with errexit suppressed by the
# `if` — each builder validates independently, so fixing only one still leaves a
# route from a refused manifest to a written plan.
if build_forward_plan "$REFUSE_EVID/leftover.tsv" "$REFUSE_EVID/forward.sql" \
        "$ROOT/db/migrations/010_postgresql_least_privilege.sql" >/dev/null 2>&1; then
    db_psql -c 'DROP DATABASE avelren_leftover_test' >/dev/null || true
    fail 'forward plan must not be generated while an unexpected database exists'
fi
[ ! -s "$REFUSE_EVID/forward.sql" ] || { db_psql -c 'DROP DATABASE avelren_leftover_test' >/dev/null || true
    fail 'refused manifest still produced a forward plan'; }
if build_inverse_plan "$REFUSE_EVID/leftover.tsv" "$REFUSE_EVID/inverse.sql" >/dev/null 2>&1; then
    db_psql -c 'DROP DATABASE avelren_leftover_test' >/dev/null || true
    fail 'inverse plan must not be generated while an unexpected database exists'
fi
[ ! -s "$REFUSE_EVID/inverse.sql" ] || { db_psql -c 'DROP DATABASE avelren_leftover_test' >/dev/null || true
    fail 'refused manifest still produced an inverse plan'; }
db_psql -c 'DROP DATABASE avelren_leftover_test' >/dev/null || fail 'leftover fixture cleanup failed'
echo 'bootstrap-topology unexpected-database refusal: PASS'

# ---- 3. forward adoption (plans applied in-transaction) -----------------------
echo '>>> forward adoption: build + apply plans, verify ownership'
EVID="$WORK/evidence"; mkdir -p "$EVID"; chmod 700 "$EVID"
export AVELREN_EVIDENCE_DIR="$EVID"
prepare_evidence_dir "$EVID"
ORIG="$EVID/original.tsv"; FWD="$EVID/forward.sql"; INV="$EVID/inverse.sql"
capture_manifest "$LEGACY_DSN" "$ORIG"
validate_owned_object_allowlist "$ORIG"
build_forward_plan "$ORIG" "$FWD" "$ROOT/db/migrations/010_postgresql_least_privilege.sql"
build_inverse_plan "$ORIG" "$INV"

# Rigorous exact round-trip: apply forward + verifier + inverse in a single
# rolled-back transaction and prove the recaptured manifest is byte-identical to
# ORIG, with the catalog left unchanged. This is the strict "inverse restores the
# exact baseline" proof, run BEFORE any committed runtime activity so intervening
# TimescaleDB chunk creation cannot perturb the comparison.
validate_plan_round_trip "$LEGACY_DSN" "$ORIG" "$FWD" "$INV" \
    || fail 'exact forward/inverse round-trip (rolled back) did not restore ORIG'
echo 'bootstrap-topology exact round-trip (rolled back, byte-identical): PASS'

# Apply forward in one transaction with the verifier appended, exactly like the
# committed adoption driver, then COMMIT. A verifier failure aborts the tx.
{
    printf '%s\n' '\set ON_ERROR_STOP on' 'BEGIN;'
    cat "$FWD"
    _target_ownership_sql "$ORIG"
    printf '%s\n' "SELECT 'FORWARD_OK';" 'COMMIT;'
} | db_psql >/dev/null || fail 'forward plan + verifier failed'

# External cross-checks of the committed ownership.
[ "$(db_psql -c "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind IN ('r','S','v') AND pg_get_userbyid(c.relowner)='avelren_migrator'")" = 20 ] \
    || fail 'not exactly 20 canonical relations owned by migrator after forward'
[ "$(db_psql -c "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=current_database()")" = avelren ] || fail 'database owner changed'
# In the bootstrap-superuser topology the public schema is owned by the virtual
# pg_database_owner role (verified on production), and adoption must leave that
# untouched — it is never reassigned to avelren directly.
[ "$(db_psql -c "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname='public'")" = pg_database_owner ] || fail 'public schema owner changed'
[ "$(db_psql -c "SELECT pg_get_userbyid(extowner) FROM pg_extension WHERE extname='timescaledb'")" = avelren ] || fail 'extension owner changed'
# Decision B / Option A: adoption's TimescaleDB-aware closure legitimately moves
# the adopted hypertables' managed internals (chunks + cagg materialisation in
# _timescaledb_internal) to avelren_migrator — the in-transaction verifier proves
# that transfer is exactly the closure. The external invariants that remain are:
# (a) the protected TS extension-catalog schemas are owned by nobody but avelren,
# and (b) avelren_admin owns nothing anywhere in the TimescaleDB surface,
# including _timescaledb_internal.
[ "$(db_psql -c "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('_timescaledb_catalog','_timescaledb_config','_timescaledb_functions','_timescaledb_cache','_timescaledb_debug','timescaledb_information','timescaledb_experimental') AND pg_get_userbyid(c.relowner) IN ('avelren_migrator','avelren_admin')")" = 0 ] \
    || fail 'migrator/admin own protected timescale catalog after forward'
[ "$(db_psql -c "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname LIKE '_timescaledb%' AND pg_get_userbyid(c.relowner)='avelren_admin'")" = 0 ] \
    || fail 'admin owns timescale internals after forward'
echo 'bootstrap-topology forward adoption + verifier: PASS'

# ---- 4. privilege contract ---------------------------------------------------
# The watchdog privilege contracts drive `no_data` health detection, which only
# fires when a checkpoint has no recent observations. Clear the setup fixture row
# (as the migrator that now owns the hypertable — also proving migrator DELETE)
# so those contracts see the empty-observations state they assert against. The
# TimescaleDB runtime section below re-inserts its own rows, so this does not
# disturb the cascade adoption already verified above.
db_psql_role avelren_migrator "$MIGRATOR_PW" \
    -c "DELETE FROM public.observations WHERE checkpoint_id = -1" >/dev/null \
    || fail 'migrator could not clear fixture observations before privilege_contracts'
echo '>>> privilege_contracts (frozen ACL) against the adopted db'
DATABASE_URL="$MIGRATOR_DSN" ADMIN_DATABASE_URL="$ADMIN_TOOL_DSN" MIGRATOR_DATABASE_URL="$MIGRATOR_DSN" \
BACKUP_DATABASE_URL="$BACKUP_DSN" COLLECTOR_DATABASE_URL="$COLLECTOR_DSN" NOTIFIER_DATABASE_URL="$NOTIFIER_DSN" \
WATCHDOG_DATABASE_URL="$WATCHDOG_DSN" API_DATABASE_URL="$API_DSN" \
real_compose run --rm --no-deps -T \
    -e DATABASE_URL -e ADMIN_DATABASE_URL -e MIGRATOR_DATABASE_URL -e BACKUP_DATABASE_URL \
    -e COLLECTOR_DATABASE_URL -e NOTIFIER_DATABASE_URL -e WATCHDOG_DATABASE_URL -e API_DATABASE_URL -e AVELREN_TEST_DB=1 \
    test python -m pytest app/tests/test_db_privileges.py -q -p no:cacheprovider >/dev/null \
    || fail 'privilege_contracts failed after bootstrap-topology adoption'
echo 'bootstrap-topology privilege_contracts: PASS'

# ---- 4.5 the PRODUCTION gate's exact pytest invocation ------------------------
# The step above is the developer-shaped run: it supplies DATABASE_URL and
# AVELREN_TEST_DB=1, so app/tests/conftest.py's destructive-suite guard is
# satisfied. The production gate (deploy/postgres-privilege-gate.sh) cannot do
# that — the guard also demands a database name containing test/ci, and the live
# database is `avelren`. Satisfying it would disable the very safeguard that
# keeps DELETE-running tests away from production, so the gate uses
# `--noconftest` instead.
#
# Regression 2026-08-14: the gate shipped WITHOUT that flag and aborted with
# `Exit: DATABASE_URL не задано` (rc=3) before a single assertion, failing the
# post-commit acceptance and rolling back a correctly committed adoption. It was
# never caught because the gate's own contract test drives a FAKE docker (argv
# assertions only) and CI merely `bash -n`-checked it — the real pytest
# invocation had never run anywhere.
#
# So reproduce that invocation faithfully here, against a real adopted database:
# the same seven introspection-only tests, the same --noconftest, and
# deliberately NO DATABASE_URL and NO AVELREN_TEST_DB. If conftest is ever
# required again, or one of these tests grows a conftest fixture, this fails.
echo '>>> production gate pytest invocation (no conftest, no DATABASE_URL)'
GATE_TESTS=app/tests/test_db_privileges.py
ADMIN_DATABASE_URL="$ADMIN_TOOL_DSN" BACKUP_DATABASE_URL="$BACKUP_DSN" \
COLLECTOR_DATABASE_URL="$COLLECTOR_DSN" NOTIFIER_DATABASE_URL="$NOTIFIER_DSN" \
WATCHDOG_DATABASE_URL="$WATCHDOG_DSN" API_DATABASE_URL="$API_DSN" \
real_compose run --rm --no-deps -T \
    -e ADMIN_DATABASE_URL -e BACKUP_DATABASE_URL -e COLLECTOR_DATABASE_URL \
    -e NOTIFIER_DATABASE_URL -e WATCHDOG_DATABASE_URL -e API_DATABASE_URL \
    test python -m pytest -q -p no:cacheprovider --noconftest \
        "$GATE_TESTS::test_role_has_no_elevated_capability" \
        "$GATE_TESTS::test_table_privileges_match_frozen_acl" \
        "$GATE_TESTS::test_sequence_privileges_match_frozen_acl" \
        "$GATE_TESTS::test_device_column_privileges_match_frozen_acl" \
        "$GATE_TESTS::test_column_scoped_updates_match_frozen_acl" \
        "$GATE_TESTS::test_column_scoped_selects_match_frozen_acl" \
        "$GATE_TESTS::test_public_has_no_existing_application_object_privileges" >/dev/null \
    || fail 'production gate pytest invocation failed (the 2026-08-14 regression)'
echo 'bootstrap-topology production-gate invocation: PASS'

# ---- 5. TimescaleDB runtime, before and after avelren -> NOLOGIN --------------
# The continuous-aggregate view is owned by migrator, but its materialisation
# hypertable + chunks stay owned by avelren. Prove that hypertable operations
# still work — and keep working once the legacy avelren owner is NOLOGIN.
timescale_runtime() {
    local phase=$1
    # collector inserts an observation (routes into a chunk owned by avelren).
    db_psql_role avelren_collector "$COLLECTOR_PW" -c \
        "INSERT INTO public.observations (time, checkpoint_id, wait_time_seconds, vehicles_in_queue, is_paused) VALUES (now(), -1, 42, 2, false)" >/dev/null \
        || fail "[$phase] collector insert failed"
    # migrator (hypertable owner) drives retention, compression and cagg refresh.
    db_psql_role avelren_migrator "$MIGRATOR_PW" <<'SQL' >/dev/null || fail "[$phase] timescale maintenance failed"
CALL refresh_continuous_aggregate('public.observations_hourly', NULL, NULL);
SELECT add_retention_policy('public.observations', INTERVAL '3650 days', if_not_exists => true);
SELECT remove_retention_policy('public.observations', if_exists => true);
ALTER TABLE public.observations SET (timescaledb.compress, timescaledb.compress_orderby = 'time DESC');
ALTER TABLE public.observations SET (timescaledb.compress = false);
SQL
    # new chunk creation: force a row far outside the existing chunk window.
    db_psql_role avelren_collector "$COLLECTOR_PW" -c \
        "INSERT INTO public.observations (time, checkpoint_id, wait_time_seconds, vehicles_in_queue, is_paused) VALUES (now() + INTERVAL '200 years', -1, 7, 1, false)" >/dev/null \
        || fail "[$phase] new-chunk insert failed"
    echo "timescale runtime [$phase]: PASS"
}

timescale_runtime post-adoption

echo '>>> retiring legacy avelren -> NOLOGIN, re-running timescale runtime'
db_psql -c "ALTER ROLE avelren NOLOGIN" >/dev/null
[ "$(db_psql_role avelren_admin "$ADMIN_PW" -c "SELECT rolcanlogin::text FROM pg_roles WHERE rolname='avelren'")" = false ] \
    || fail 'avelren is not NOLOGIN'
timescale_runtime post-nologin
# Restore LOGIN so the inverse round-trip returns to the exact baseline.
db_psql_role avelren_admin "$ADMIN_PW" -c "ALTER ROLE avelren LOGIN" >/dev/null

# ---- 6. committed inverse: full ownership restoration -----------------------
# The exact byte-identical round-trip was already proven above in a rolled-back
# transaction. Here we apply the inverse over the COMMITTED forward state — after
# the runtime section has legitimately created new TimescaleDB chunks — so an
# exact manifest cmp against the pre-runtime ORIG is neither possible nor
# meaningful (new chunks are real data-plane objects, not an ownership defect).
# The invariant that matters is ownership restoration: every adopted object,
# including the newly-created chunks, returns to the legacy avelren, and no
# adoption role retains ownership of anything.
echo '>>> committed inverse: full ownership restoration to legacy avelren'
{
    printf '%s\n' '\set ON_ERROR_STOP on' 'BEGIN;'
    cat "$INV"
    printf '%s\n' "SELECT 'INVERSE_OK';" 'COMMIT;'
} | db_psql >/dev/null || fail 'inverse plan failed'
[ "$(db_psql -c "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' AND c.relkind IN ('r','S','v') AND pg_get_userbyid(c.relowner)='avelren'")" = 20 ] \
    || fail 'canonical relations not returned to avelren after inverse'
# No adoption role owns ANY relation after inverse (subsumes the migrator check
# and also catches an orphaned chunk left on migrator/admin).
[ "$(db_psql -c "SELECT count(*) FROM pg_class WHERE relowner IN (SELECT oid FROM pg_roles WHERE rolname IN ('avelren_admin','avelren_migrator','avelren_backup','avelren_collector','avelren_notifier','avelren_watchdog','avelren_api'))")" = 0 ] \
    || fail 'an adoption role still owns objects after inverse'
# Every TimescaleDB internal object (including chunks created during the runtime
# section) is owned by the legacy avelren — none stranded on an adoption role.
[ "$(db_psql -c "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname LIKE '_timescaledb%' AND pg_get_userbyid(c.relowner) <> 'avelren'")" = 0 ] \
    || fail 'timescale internals not fully returned to avelren after inverse'
echo 'bootstrap-topology committed inverse (full ownership restoration): PASS'

echo 'postgres adoption bootstrap-topology integration: PASS'
