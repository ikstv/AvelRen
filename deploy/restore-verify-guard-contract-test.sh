#!/usr/bin/env bash
# Regression guard for the 2026-08-14 incident: restore-verify.sh recreated the
# live production `avelren-db-1` container because it ran in the production
# Compose project and `docker compose run` reconciled the drifted `db`
# dependency. These cases lock in the two structural defenses:
#   1. disposable verification refuses in (or without) the production project;
#   2. every `docker compose run` carries --no-deps, so `db` is never started or
#      reconciled — no production container can be recreated.
#
# The tests use a fake `docker` on PATH that records every argv it receives, so
# they assert exactly which Compose lifecycle commands would run — no real
# Docker, no real containers, safe in CI.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

BIN="$WORK/bin"
mkdir -p "$BIN"
# Records each invocation's argv; a `run` succeeds (exit 0) so the script would
# proceed through both verification steps. Any up/down/create/recreate/stop is
# recorded too, so the assertions below can prove they never happen.
cat >"$BIN/docker" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"${FAKE_LOG:?}"
exit 0
SH
chmod +x "$BIN/docker"

MIGRATOR_DSN='postgresql://avelren_migrator:guard-secret@db:5432/restore_test'
API_DSN='postgresql://avelren_api:guard-secret@db:5432/restore_test'

# Common environment for a would-be verification run. STACK_DIR points at the
# repo so a bare `docker compose` (were it reached) would resolve the production
# project name from the directory — which is exactly what the guard must block.
run_verify() {
    env PATH="$BIN:$PATH" FAKE_LOG="$FAKE_LOG" \
        AVELREN_STACK_DIR="$ROOT" \
        AVELREN_VERIFY_MIGRATOR_DSN="$MIGRATOR_DSN" \
        AVELREN_VERIFY_API_DSN="$API_DSN" \
        AVELREN_PRODUCTION_COMPOSE_PROJECT=avelren \
        "$@" \
        bash "$ROOT/deploy/restore-verify.sh" restore_test
}

fail() { echo "GUARD TEST FAILED: $*" >&2; exit 1; }

# --- A: PRODUCTION PROJECT GUARD — no project set -------------------------------
# An unset Compose project would resolve to the production project on the prod
# host. The script must refuse before any docker command runs.
FAKE_LOG="$WORK/a.log"; : >"$FAKE_LOG"
if run_verify >"$WORK/a.out" 2>&1; then
    cat "$WORK/a.out" >&2; fail 'A: unset project was not refused'
fi
grep -q 'explicit non-production Compose project' "$WORK/a.out" || {
    cat "$WORK/a.out" >&2; fail 'A: wrong refusal message for unset project'
}
[ ! -s "$WORK/a.log" ] || fail 'A: a docker command ran before the project guard refused'
echo 'A production-project guard (unset project): PASS'

# --- A2: PRODUCTION PROJECT GUARD — project explicitly = production -------------
FAKE_LOG="$WORK/a2.log"; : >"$FAKE_LOG"
if run_verify AVELREN_COMPOSE_PROJECT=avelren >"$WORK/a2.out" 2>&1; then
    cat "$WORK/a2.out" >&2; fail 'A2: production project was not refused'
fi
grep -q 'must not run in the production Compose project' "$WORK/a2.out" || {
    cat "$WORK/a2.out" >&2; fail 'A2: wrong refusal message for production project'
}
[ ! -s "$WORK/a2.log" ] || fail 'A2: a docker command ran before the production-project guard refused'
echo 'A2 production-project guard (explicit production project): PASS'

# --- B: DISPOSABLE PROJECT — proceeds ------------------------------------------
# An explicit non-production project is accepted and the script drives both
# verification steps through docker.
FAKE_LOG="$WORK/b.log"; : >"$FAKE_LOG"
run_verify AVELREN_COMPOSE_PROJECT=restore-verify-disposable >"$WORK/b.out" 2>&1 || {
    cat "$WORK/b.out" >&2; fail 'B: disposable project run did not succeed'
}
[ "$(grep -c ' run --rm --no-deps -T ' "$WORK/b.log")" -eq 2 ] || {
    cat "$WORK/b.log" >&2; fail 'B: expected exactly two verification run commands'
}
grep -q -- '-p restore-verify-disposable ' "$WORK/b.log" || {
    cat "$WORK/b.log" >&2; fail 'B: verification did not run under the disposable project'
}
echo 'B disposable project proceeds: PASS'

# --- C: PRODUCTION CONTAINER IDENTITY — no lifecycle command can recreate db ----
# Structural stand-in for "production db container ID unchanged": prove the
# script never issues a Compose command that could start/recreate/stop a
# service, and that every `run` is --no-deps (so `db` is never reconciled).
# Reusing B's recorded log — those are ALL the docker commands the run made.
if grep -Eq '(^| )(up|down|create|recreate|start|stop|restart)( |$)' "$WORK/b.log"; then
    cat "$WORK/b.log" >&2
    fail 'C: a service-lifecycle Compose command was issued (could recreate production db)'
fi
if grep -q ' run ' "$WORK/b.log" && ! grep -q ' run --rm --no-deps -T ' "$WORK/b.log"; then
    fail 'C: a run command without --no-deps was issued (could reconcile db)'
fi
# No `run` line may omit --no-deps.
while IFS= read -r line; do
    case " $line " in
        *' run '*)
            case " $line " in
                *' --no-deps '*) ;;
                *) fail "C: run without --no-deps: $line" ;;
            esac
            ;;
    esac
done <"$WORK/b.log"
echo 'C production container identity (no recreate-capable command): PASS'

# --- D: CONFIG-DRIFT REGRESSION -------------------------------------------------
# The incident's precondition was a disposable/on-disk config differing from the
# running production container. Even with such drift present, the guard + the
# --no-deps invocations mean the production db is never reconciled. We simulate
# drift by pointing at a compose file that differs from any running container;
# the disposable path must still emit only --no-deps runs and zero lifecycle
# commands, and the production-project path must still be refused outright.
DRIFT_COMPOSE="$WORK/drift-compose.yml"
cat >"$DRIFT_COMPOSE" <<'YML'
services:
  db:
    image: timescale/timescaledb:2.17.2-pg16
    mem_limit: 999m
  migrate:
    image: avelren-app:latest
    depends_on:
      db:
        condition: service_healthy
  api:
    image: avelren-app:latest
    depends_on:
      db:
        condition: service_healthy
YML
# D1: production project + drift → still refused before any docker command.
FAKE_LOG="$WORK/d1.log"; : >"$FAKE_LOG"
if run_verify AVELREN_COMPOSE_FILE="$DRIFT_COMPOSE" AVELREN_COMPOSE_PROJECT=avelren \
    >"$WORK/d1.out" 2>&1; then
    cat "$WORK/d1.out" >&2; fail 'D1: production project with drift was not refused'
fi
[ ! -s "$WORK/d1.log" ] || fail 'D1: a docker command ran despite production-project refusal under drift'
# D2: disposable project + drift → proceeds, but only --no-deps runs, no lifecycle.
FAKE_LOG="$WORK/d2.log"; : >"$FAKE_LOG"
run_verify AVELREN_COMPOSE_FILE="$DRIFT_COMPOSE" \
    AVELREN_COMPOSE_PROJECT=restore-verify-disposable >"$WORK/d2.out" 2>&1 || {
    cat "$WORK/d2.out" >&2; fail 'D2: disposable drift run did not succeed'
}
if grep -Eq '(^| )(up|down|create|recreate|start|stop|restart)( |$)' "$WORK/d2.log"; then
    cat "$WORK/d2.log" >&2
    fail 'D2: a service-lifecycle command was issued under drift (could recreate db)'
fi
[ "$(grep -c ' run --rm --no-deps -T ' "$WORK/d2.log")" -eq 2 ] || {
    cat "$WORK/d2.log" >&2; fail 'D2: expected exactly two --no-deps run commands under drift'
}
echo 'D config-drift regression (production refused, disposable never reconciles db): PASS'

echo 'restore-verify guard contract: ALL PASS'
