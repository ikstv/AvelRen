#!/usr/bin/env bash
# Public low-level restore CLI. It intentionally supports only restore_test.
set -euo pipefail

STACK_DIR=${AVELREN_STACK_DIR:-/opt/avelren}
COMPOSE_FILE=${AVELREN_COMPOSE_FILE:-}
COMPOSE_PROJECT=${AVELREN_COMPOSE_PROJECT:-}
DB_SERVICE=${AVELREN_DB_SERVICE:-db}
DUMP=${1:?specify the dump file}
shift
TARGET=restore_test
DRY_RUN=false

while [ "$#" -gt 0 ]; do
    case "$1" in
        --target)
            [ "$#" -ge 2 ] || { echo "error: --target requires a value" >&2; exit 2; }
            TARGET=$2; shift 2 ;;
        --confirm-production-restore)
            # Parse the historical option only to return an explicit fail-closed denial.
            [ "$#" -ge 2 ] || { echo "error: confirmation token is missing" >&2; exit 2; }
            shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        *) echo "error: unknown argument: $1" >&2; exit 2 ;;
    esac
done

log() { echo "$(date -u +%FT%TZ) $*"; }
[ -f "$DUMP" ] || { log "DENIED: backup artifact not found: $DUMP"; exit 1; }
if [ "$TARGET" != restore_test ]; then
    log "DENIED: direct production restore is forbidden; use deploy/restore-production.sh"
    exit 2
fi
gzip -t "$DUMP" || { log "DENIED: backup artifact failed gzip integrity validation"; exit 1; }

log "preflight OK: target=$TARGET, backup=$DUMP"
if [ "$DRY_RUN" = true ]; then
    log "dry-run: destructive restore was not performed"
    exit 0
fi

# shellcheck source=deploy/restore-engine.lib.sh
source "$STACK_DIR/deploy/restore-engine.lib.sh"
avelren_restore_engine "$DUMP" "$TARGET" "$STACK_DIR" "$COMPOSE_FILE" "$COMPOSE_PROJECT" "$DB_SERVICE"
