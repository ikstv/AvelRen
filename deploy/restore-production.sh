#!/usr/bin/env bash
# Controlled production-only restore orchestrator. Never used for restore_test.
set -euo pipefail

STACK_DIR=${AVELREN_STACK_DIR:-/opt/avelren}
COMPOSE_FILE=${AVELREN_COMPOSE_FILE:-}
COMPOSE_PROJECT=${AVELREN_COMPOSE_PROJECT:-}
DB_SERVICE=${AVELREN_DB_SERVICE:-db}
VERIFY_APP_SERVICE=${AVELREN_VERIFY_APP_SERVICE:-migrate}
INGRESS_SERVICE=${AVELREN_INGRESS_SERVICE:-caddy}
KNOWN_CLIENTS=${AVELREN_DB_CLIENT_SERVICES:-api collector notifier watchdog}
READINESS_URL=${AVELREN_READINESS_URL:-https://api.bordersignal.pp.ua/health}
READINESS_TIMEOUT=${AVELREN_READINESS_TIMEOUT_SECONDS:-120}
FRESHNESS_TIMEOUT=${AVELREN_FRESHNESS_TIMEOUT_SECONDS:-180}
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
db_psql() { compose exec -T "$DB_SERVICE" psql -U avelren "$@"; }

if [ "$CONFIRMATION" != "$CONFIRMATION_TOKEN" ]; then
    log "ВІДМОВА: production orchestrator потребує exact confirmation token"
    exit 2
fi
[ -f "$DUMP" ] || { log "ВІДМОВА: backup artifact не знайдено"; exit 1; }
gzip -t "$DUMP" || { log "ВІДМОВА: backup artifact corrupt"; exit 1; }

cd "$STACK_DIR"
SUCCESS=false
keep_maintenance_on_failure() {
    local status=$?
    trap - EXIT HUP INT TERM
    if [ "$SUCCESS" != true ]; then
        set +e
        compose stop "$INGRESS_SERVICE" >/dev/null 2>&1
        # shellcheck disable=SC2086
        compose stop $KNOWN_CLIENTS >/dev/null 2>&1
        set -e
        log "RESTORE FAILED (exit=$status): ingress і DB clients залишені stopped"
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

session_count=$(db_psql -d postgres -At -v target="$PRODUCTION_TARGET" -c \
    "SELECT count(*) FROM pg_stat_activity
     WHERE datname = :'target' AND pid <> pg_backend_pid();")
if [ "$session_count" != 0 ]; then
    log "ВІДМОВА: production target має active sessions: $session_count"
    db_psql -d postgres -P pager=off -c \
        "SELECT pid, usename, application_name, client_addr, state
         FROM pg_stat_activity
         WHERE datname = '$PRODUCTION_TARGET' AND pid <> pg_backend_pid()
         ORDER BY pid;" >&2 || true
    exit 1
fi

log "session gate clean; invoking low-level restore engine"
AVELREN_STACK_DIR="$STACK_DIR" \
AVELREN_COMPOSE_FILE="$COMPOSE_FILE" \
AVELREN_COMPOSE_PROJECT="$COMPOSE_PROJECT" \
AVELREN_DB_SERVICE="$DB_SERVICE" \
bash "$STACK_DIR/deploy/restore.sh" "$DUMP" --target "$PRODUCTION_TARGET" \
    --confirm-production-restore "$CONFIRMATION_TOKEN"

log "physical schema і read-only application verification"
AVELREN_STACK_DIR="$STACK_DIR" \
AVELREN_COMPOSE_FILE="$COMPOSE_FILE" \
AVELREN_COMPOSE_PROJECT="$COMPOSE_PROJECT" \
AVELREN_VERIFY_APP_SERVICE="$VERIFY_APP_SERVICE" \
AVELREN_VERIFY_MIGRATIONS_DIR="${AVELREN_VERIFY_MIGRATIONS_DIR:-/migrations}" \
AVELREN_PRODUCTION_VERIFY_CONTEXT=AVELREN-INTERNAL-PRODUCTION-VERIFY \
AVELREN_VERIFY_DATABASE_URL="${AVELREN_VERIFY_DATABASE_URL:-}" \
bash "$STACK_DIR/deploy/restore-verify.sh" "$PRODUCTION_TARGET"

log "controlled restart: migrate gate"
compose up -d migrate
compose wait migrate

log "controlled restart: DB clients"
# shellcheck disable=SC2086
compose up -d $KNOWN_CLIENTS
log "maintenance exit: starting ingress last"
compose up -d "$INGRESS_SERVICE"

deadline=$((SECONDS + READINESS_TIMEOUT))
until curl --fail --silent --show-error --max-time 10 "$READINESS_URL" >/dev/null; do
    [ "$SECONDS" -lt "$deadline" ] || {
        log "ПОМИЛКА: canonical API readiness timeout: $READINESS_URL"; exit 1;
    }
    sleep 2
done

fresh_deadline=$((SECONDS + FRESHNESS_TIMEOUT))
until fresh=$(db_psql -d "$PRODUCTION_TARGET" -At -c \
    "SELECT EXISTS (SELECT 1 FROM observations WHERE time > now() - INTERVAL '3 minutes');") \
    && [ "$fresh" = t ]; do
    [ "$SECONDS" -lt "$fresh_deadline" ] || {
        log "ПОМИЛКА: collector freshness timeout after restore"; exit 1;
    }
    sleep 5
done

SUCCESS=true
log "production restore complete: schema/app/HTTPS/freshness verified"
