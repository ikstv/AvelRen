#!/usr/bin/env bash
# Exercise the real stop/inspect path with sleeping disposable containers.
# No application, database, upstream, or production project is used.
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
WORK=$(mktemp -d)
PROJECT="avelren-failure-state-${RANDOM}-${RANDOM}"
COMPOSE_FILE="$WORK/compose.yml"
if command -v cygpath >/dev/null 2>&1; then COMPOSE_FILE=$(cygpath -w "$COMPOSE_FILE"); fi
export PROJECT COMPOSE_FILE MSYS_NO_PATHCONV=1
compose() { docker compose -p "$PROJECT" -f "$COMPOSE_FILE" "$@"; }
cleanup() {
    local status=$?
    trap - EXIT
    compose down --volumes --remove-orphans >/dev/null 2>&1 || true
    rm -rf -- "$WORK"
    exit "$status"
}
trap cleanup EXIT
cat >"$WORK/compose.yml" <<'YAML'
x-fixture: &fixture
  image: timescale/timescaledb:2.30.1-pg16@sha256:f495f2bc25ca7596ca8e1606c6241ca250ccc56a0c082b9f2ec0d290e0126cd9
  entrypoint: [/bin/sh, -c]
  command: ["sleep 3600"]
  network_mode: none
  cap_drop: [ALL]
  security_opt: ["no-new-privileges:true"]
services:
  caddy: *fixture
  api: *fixture
  collector: *fixture
  notifier: *fixture
  watchdog: *fixture
  db: *fixture
YAML
compose up -d
db_id=$(compose ps --quiet db)
set +e
bash -c '
    source "$1/ops/restore-production.sh"
    avelren_compose() { docker compose -p "$PROJECT" -f "$COMPOSE_FILE" "$@"; }
    AVELREN_RESTORE_MAINTENANCE_STARTED=true
    AVELREN_RESTORE_PHASE=restored
    trap avelren_restore_exit_trap EXIT
    exit 71
' bash "$ROOT" >"$WORK/result.log" 2>&1
status=$?
set -e
[ "$status" -eq 71 ] || { cat "$WORK/result.log"; exit 1; }
grep -q '^failure_state=stopped-verified$' "$WORK/result.log" || { cat "$WORK/result.log"; exit 1; }
for service in caddy api collector notifier watchdog; do
    id=$(compose ps --all --quiet "$service")
    [ -n "$id" ]
    [ "$(docker inspect --format '{{.State.Status}}' "$id")" = exited ]
done
[ "$(compose ps --quiet db)" = "$db_id" ]
[ "$(docker inspect --format '{{.State.Status}}' "$db_id")" = running ]
echo 'restore failure-state integration: PASS (5 clients stopped, DB sentinel unchanged, exit 71 preserved)'
