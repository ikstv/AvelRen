#!/usr/bin/env bash
# Controlled production-only restore orchestrator. Never used for restore_test.
set -euo pipefail

STACK_DIR=${AVELREN_STACK_DIR:-/opt/avelren}
COMPOSE_FILE=${AVELREN_COMPOSE_FILE:-}
COMPOSE_PROJECT=${AVELREN_COMPOSE_PROJECT:-}
DB_SERVICE=${AVELREN_DB_SERVICE:-db}
VERIFY_SCHEMA_SERVICE=${AVELREN_VERIFY_SCHEMA_SERVICE:-migrate}
VERIFY_API_SERVICE=${AVELREN_VERIFY_API_SERVICE:-api}
API_SERVICE=${AVELREN_API_SERVICE:-api}
INGRESS_SERVICE=${AVELREN_INGRESS_SERVICE:-caddy}
KNOWN_CLIENTS=${AVELREN_DB_CLIENT_SERVICES:-api collector notifier watchdog}
READINESS_URL=${AVELREN_READINESS_URL:-https://api.bordersignal.pp.ua/api/health}
READINESS_TIMEOUT=${AVELREN_READINESS_TIMEOUT_SECONDS:-120}
FRESHNESS_TIMEOUT=${AVELREN_FRESHNESS_TIMEOUT_SECONDS:-180}
ADMIN_DB_USER=${AVELREN_ADMIN_DB_USER:-avelren_admin}
ADMIN_DB_PASSWORD=${AVELREN_ADMIN_PASSWORD:-}
ADMIN_DATABASE_URL=${AVELREN_ADMIN_DSN:-}
MIGRATOR_DATABASE_URL=${AVELREN_MIGRATOR_DSN:-}
API_DATABASE_URL=${AVELREN_API_DSN:-}
PRODUCTION_TARGET=avelren
CONFIRMATION_TOKEN=AVELREN-PRODUCTION-RESTORE

DUMP=${1:?вкажіть backup artifact}
shift
CONFIRMATION=
while [ "$#" -gt 0 ]; do
    case "$1" in
        --confirm-production-restore)
            [ "$#" -ge 2 ] || { echo "confirmation token відсутній" >&2; exit 2; }
            CONFIRMATION=$2; shift 2
            ;;
        *) echo "невідомий аргумент: $1" >&2; exit 2 ;;
    esac
done

log() { echo "$(date -u +%FT%TZ) $*"; }
compose() {
    local args=(docker compose)
    [ -z "$COMPOSE_FILE" ] || args+=(-f "$COMPOSE_FILE")
    [ -z "$COMPOSE_PROJECT" ] || args+=(-p "$COMPOSE_PROJECT")
    "${args[@]}" "$@"
}
db_psql() {
    PGPASSWORD="$ADMIN_DB_PASSWORD" compose exec -T -e PGPASSWORD "$DB_SERVICE" \
        psql -U "$ADMIN_DB_USER" -v ON_ERROR_STOP=1 "$@"
}
admin_dsn_current_user() {
    local base="$ADMIN_DATABASE_URL" query="" maintenance_dsn
    case "$base" in
        postgresql://*/*) ;;
        *) return 2 ;;
    esac
    if [[ "$base" == *\?* ]]; then
        query="?${base#*\?}"
        base=${base%%\?*}
    fi
    maintenance_dsn="${base%/*}/postgres${query}"
    AVELREN_ADMIN_DSN="$maintenance_dsn" compose exec -T -e AVELREN_ADMIN_DSN \
        "$DB_SERVICE" sh -c \
        'psql -X --no-psqlrc --tuples-only --no-align --dbname="$AVELREN_ADMIN_DSN" -c "SELECT current_user"'
}

if [ "$CONFIRMATION" != "$CONFIRMATION_TOKEN" ]; then
    log "ВІДМОВА: production orchestrator потребує exact confirmation token"
    exit 2
fi
[ -f "$DUMP" ] || { log "ВІДМОВА: backup artifact не знайдено"; exit 1; }
gzip -t "$DUMP" || { log "ВІДМОВА: backup artifact corrupt"; exit 1; }

[ "$ADMIN_DB_USER" = avelren_admin ] || {
    log "restore database role must be avelren_admin"; exit 2;
}
[ -n "$ADMIN_DB_PASSWORD" ] || {
    log "restore database password is required"; exit 2;
}
[ -n "$ADMIN_DATABASE_URL" ] || {
    log "admin verification DSN is required"; exit 2;
}
[ -n "$MIGRATOR_DATABASE_URL" ] || {
    log "migrator verification DSN is required"; exit 2;
}
[ -n "$API_DATABASE_URL" ] || {
    log "API verification DSN is required"; exit 2;
}

cd "$STACK_DIR"
admin_current_user=$(admin_dsn_current_user) || {
    log "admin verification DSN connection failed"
    exit 2
}
[ "$admin_current_user" = avelren_admin ] || {
    log "admin verification DSN must authenticate as avelren_admin"
    exit 2
}

SUCCESS=false
keep_maintenance_on_failure() {
    local status=$?
    local cleanup_failed=false running service
    trap - EXIT HUP INT TERM
    if [ "$SUCCESS" != true ]; then
        set +e
        if ! compose stop "$INGRESS_SERVICE"; then
            log "ПОМИЛКА: cleanup stop failed: $INGRESS_SERVICE"
            cleanup_failed=true
        fi
        # shellcheck disable=SC2086
        if ! compose stop $KNOWN_CLIENTS; then
            log "ПОМИЛКА: cleanup stop failed: $KNOWN_CLIENTS"
            cleanup_failed=true
        fi
        if running=$(compose ps --status running --services); then
            for service in $INGRESS_SERVICE $KNOWN_CLIENTS; do
                if printf '%s\n' "$running" | grep -Fxq "$service"; then
                    log "ПОМИЛКА: cleanup left service running: $service"
                    cleanup_failed=true
                fi
            done
        else
            log "ПОМИЛКА: cleanup could not verify final service state"
            cleanup_failed=true
        fi
        set -e
        if [ "$cleanup_failed" = true ]; then
            log "RESTORE FAILED (exit=$status): maintenance cleanup incomplete; manual intervention required"
        else
            log "RESTORE FAILED (exit=$status): ingress і DB clients залишені stopped"
        fi
    fi
    exit "$status"
}
trap keep_maintenance_on_failure EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

log "maintenance entry: stopping public ingress $INGRESS_SERVICE"
compose stop "$INGRESS_SERVICE"
log "quiesce: stopping known DB clients: $KNOWN_CLIENTS"
# Intentional word splitting: service names are an operator-configurable list.
# shellcheck disable=SC2086
compose stop $KNOWN_CLIENTS

running=$(compose ps --status running --services)
for service in $INGRESS_SERVICE $KNOWN_CLIENTS; do
    if printf '%s\n' "$running" | grep -Fxq "$service"; then
        log "ВІДМОВА: service досі running: $service"
        exit 1
    fi
done

session_count=$(db_psql -d postgres -At -v target="$PRODUCTION_TARGET" <<'SQL'
SELECT count(*) FROM pg_stat_activity
WHERE datname = :'target'
  AND backend_type = 'client backend'
  AND pid <> pg_backend_pid();
SQL
)
if [ "$session_count" != 0 ]; then
    log "ВІДМОВА: production target має active sessions: $session_count"
    db_psql -d postgres -P pager=off -v target="$PRODUCTION_TARGET" >&2 <<'SQL' || true
SELECT pid, usename, application_name, client_addr, state, backend_type
FROM pg_stat_activity
WHERE datname = :'target'
  AND backend_type = 'client backend'
  AND pid <> pg_backend_pid()
ORDER BY pid;
SQL
    exit 1
fi

log "session gate clean; invoking low-level restore engine"
# Production capability is structural: the engine is a source-only library and
# the public restore.sh CLI rejects every production target.
# shellcheck source=deploy/restore-engine.lib.sh
(
    # Keep the engine's EXIT trap in its own shell; the orchestrator's
    # fail-closed maintenance trap must remain authoritative here.
    source "$STACK_DIR/deploy/restore-engine.lib.sh"
    avelren_restore_engine "$DUMP" "$PRODUCTION_TARGET" "$STACK_DIR" \
        "$COMPOSE_FILE" "$COMPOSE_PROJECT" "$DB_SERVICE"
)

log "physical schema і read-only application verification"
log "controlled restart: migrate gate"
compose up -d migrate
compose wait migrate

AVELREN_STACK_DIR="$STACK_DIR" \
AVELREN_COMPOSE_FILE="$COMPOSE_FILE" \
AVELREN_COMPOSE_PROJECT="$COMPOSE_PROJECT" \
AVELREN_VERIFY_SCHEMA_SERVICE="$VERIFY_SCHEMA_SERVICE" \
AVELREN_VERIFY_API_SERVICE="$VERIFY_API_SERVICE" \
AVELREN_VERIFY_MIGRATIONS_DIR="${AVELREN_VERIFY_MIGRATIONS_DIR:-/migrations}" \
AVELREN_PRODUCTION_VERIFY_CONTEXT=AVELREN-INTERNAL-PRODUCTION-VERIFY \
AVELREN_VERIFY_MIGRATOR_DSN="$MIGRATOR_DATABASE_URL" \
AVELREN_VERIFY_API_DSN="$API_DATABASE_URL" \
bash "$STACK_DIR/deploy/restore-verify.sh" "$PRODUCTION_TARGET"

pre_restart_run=$(db_psql -d "$PRODUCTION_TARGET" -At -c \
    "SELECT COALESCE(max(time), '-infinity'::timestamptz) FROM collector_runs;")

log "controlled restart: DB clients"
# shellcheck disable=SC2086
compose up -d $KNOWN_CLIENTS
log "maintenance exit: starting ingress last"
compose up -d "$INGRESS_SERVICE"

validate_health_json() {
    printf '%s' "$1" | compose exec -T "$API_SERVICE" python -c '
import json, sys
value = json.load(sys.stdin)
if not isinstance(value, dict):
    raise SystemExit(1)
if value.get("status") not in {"ok", "stale"}:
    raise SystemExit(1)
if "last_observation" not in value or "age_seconds" not in value:
    raise SystemExit(1)
'
}

deadline=$((SECONDS + READINESS_TIMEOUT))
until health=$(curl --fail --silent --show-error --max-time 10 "$READINESS_URL") \
    && validate_health_json "$health"; do
    [ "$SECONDS" -lt "$deadline" ] || {
        log "ПОМИЛКА: canonical API readiness timeout: $READINESS_URL"; exit 1;
    }
    sleep 2
done

fresh_deadline=$((SECONDS + FRESHNESS_TIMEOUT))
until fresh=$(db_psql -d "$PRODUCTION_TARGET" -At -c \
    "SELECT EXISTS (SELECT 1 FROM collector_runs WHERE time > '$pre_restart_run' AND error IS NULL AND rows_written > 0);") \
    && [ "$fresh" = t ]; do
    [ "$SECONDS" -lt "$fresh_deadline" ] || {
        log "ПОМИЛКА: collector freshness timeout after restore"; exit 1;
    }
    sleep 5
done

running=$(compose ps --status running --services)
for service in $INGRESS_SERVICE $KNOWN_CLIENTS; do
    printf '%s\n' "$running" | grep -Fxq "$service" || {
        log "ПОМИЛКА: service не running після restore: $service"; exit 1;
    }
done

SUCCESS=true
log "production restore complete: schema/app/HTTPS/freshness verified"
