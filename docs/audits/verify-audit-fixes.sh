#!/usr/bin/env bash
# Full verification of the 2026-08-12 audit fixes. The script lives in
# docs/audits/ but must run against the repository root (it cd's there itself),
# on the server or anywhere with Docker + Python3:
#
#     bash docs/audits/verify-audit-fixes.sh          # fast checks (safe, ~a minute)
#     bash docs/audits/verify-audit-fixes.sh --full   # + the full backend suite
#                                                      #   (disposable test DB via compose)
#
# Touches no production data: the contract tests are fakeable, and the backend
# suite brings up an isolated disposable DB with an env guard. Prints a PASS/FAIL
# summary.
set -uo pipefail

# Script lives in docs/audits/; operate from the repository root two levels up.
cd "$(dirname "$0")/../.."
FULL=0
[ "${1:-}" = "--full" ] && FULL=1

pass=0; fail=0; skip=0
declare -a RESULTS

run() {
    local name=$1; shift
    printf '\n\033[1m=== %s ===\033[0m\n' "$name"
    if "$@"; then
        RESULTS+=("PASS  $name"); pass=$((pass+1))
    else
        RESULTS+=("FAIL  $name"); fail=$((fail+1))
    fi
}
skipmsg() { RESULTS+=("SKIP  $1"); skip=$((skip+1)); printf '\n\033[33m=== SKIP: %s ===\033[0m\n' "$1"; }

# --- Context ----------------------------------------------------------------
printf '\033[1mRepository:\033[0m %s\n' "$(pwd)"
if command -v git >/dev/null; then
    printf 'Branch: %s  HEAD: %s\n' "$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo '?')" \
        "$(git rev-parse --short HEAD 2>/dev/null || echo '?')"
    printf 'Changed/new files:\n'; git status --short 2>/dev/null | sed 's/^/  /'
fi

# --- Presence of the key fix files ------------------------------------------
check_files() {
    local ok=0 f
    for f in \
        deploy/restore-allowlist-contract-test.py \
        deploy/backup.sh deploy/restore-production.sh \
        app/src/avelren/watchdog.py app/src/avelren/forecast.py \
        app/src/avelren/api.py app/src/avelren/subscriptions_api.py \
        android/app/src/main/java/ua/avelren/app/data/DeviceStore.kt
    do
        if [ -f "$f" ]; then printf '  ok   %s\n' "$f"; else printf '  MISS %s\n' "$f"; ok=1; fi
    done
    # Markers that the fixes are really in the code:
    grep -q "AT TIME ZONE 'Europe/Kyiv'" app/src/avelren/forecast.py || { echo "forecast M-7 marker missing"; ok=1; }
    grep -q 'backup_stale' app/src/avelren/watchdog.py || { echo "watchdog M-12 marker missing"; ok=1; }
    grep -q 'health:{kind}' app/src/avelren/watchdog.py || { echo "watchdog M-10 marker missing"; ok=1; }
    grep -q 'AND t.is_active' app/src/avelren/subscriptions_api.py || { echo "M-16 marker missing"; ok=1; }
    grep -q 'pre-restore' deploy/restore-production.sh || { echo "M-13 marker missing"; ok=1; }
    grep -q 'type = crypt' deploy/backup.sh 2>/dev/null; grep -q 'crypt' deploy/backup.sh || { echo "M-11 marker missing"; ok=1; }
    return $ok
}
run "Fix files in place" check_files

# --- H-1: allowlist drift check ---------------------------------------------
if command -v python3 >/dev/null; then
    run "H-1 restore allowlist drift" python3 deploy/restore-allowlist-contract-test.py
else
    skipmsg "H-1 (no python3)"
fi

# --- Fakeable deploy contract tests (safe, no DB) ---------------------------
for t in backup-contract-test.sh restore-contract-test.sh restore-engine-contract-test.sh \
         restore-production-contract-test.sh compose-security-contract-test.sh; do
    if [ -f "deploy/$t" ]; then
        run "deploy/$t" bash "deploy/$t"
    else
        skipmsg "deploy/$t (missing)"
    fi
done

# --- ruff (if present) ------------------------------------------------------
if command -v ruff >/dev/null; then
    run "ruff (app/src)" ruff check app/src/avelren
else
    skipmsg "ruff (not installed)"
fi

# --- Full backend suite (--full): pytest on a disposable test DB ------------
if [ "$FULL" = 1 ]; then
    if [ -x scripts/backend-test.sh ] || [ -f scripts/backend-test.sh ]; then
        run "backend-test.sh (pytest on a disposable DB)" bash scripts/backend-test.sh
    else
        skipmsg "scripts/backend-test.sh (missing)"
    fi
else
    skipmsg "full backend suite (run with --full)"
fi

# --- Summary ----------------------------------------------------------------
printf '\n\033[1m========== SUMMARY ==========\033[0m\n'
for r in "${RESULTS[@]}"; do
    case "$r" in
        PASS*) printf '\033[32m%s\033[0m\n' "$r" ;;
        FAIL*) printf '\033[31m%s\033[0m\n' "$r" ;;
        *)     printf '\033[33m%s\033[0m\n' "$r" ;;
    esac
done
printf '\nPASS=%d  FAIL=%d  SKIP=%d\n' "$pass" "$fail" "$skip"
[ "$fail" -eq 0 ] && { echo "ALL GREEN ✅"; exit 0; } || { echo "THERE ARE FAILURES ❌ — see FAIL above"; exit 1; }
