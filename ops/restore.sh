#!/usr/bin/env bash
# Public low-level restore CLI. It intentionally supports only restore_test.
set -euo pipefail

STACK_DIR=${AVELREN_STACK_DIR:-/opt/avelren}
COMPOSE_FILE=${AVELREN_COMPOSE_FILE:-}
COMPOSE_PROJECT=${AVELREN_COMPOSE_PROJECT:-}
COMPOSE_PROJECT_DIR=${AVELREN_COMPOSE_PROJECT_DIR:-}
COMPOSE_ENV_FILE=${AVELREN_COMPOSE_ENV_FILE:-}
DB_SERVICE=${AVELREN_DB_SERVICE:-db}
ENV_GUARD=${AVELREN_COMPOSE_ENV_GUARD:-}
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
    log "DENIED: this CLI supports only the isolated restore_test database"
    exit 2
fi
if [ -z "$COMPOSE_FILE" ] || [ -z "$COMPOSE_PROJECT" ] || \
   [ -z "$COMPOSE_PROJECT_DIR" ] || [ -z "$COMPOSE_ENV_FILE" ] || \
   [ "$COMPOSE_PROJECT" = avelren ] || [ "$ENV_GUARD" != isolated ]; then
    log "DENIED: restore_test requires an explicit isolated Compose file, project, and guard"
    exit 2
fi
gzip -t "$DUMP" || { log "DENIED: backup artifact failed gzip integrity validation"; exit 1; }

log "preflight OK: target=$TARGET, backup=$DUMP"
if [ "$DRY_RUN" = true ]; then
    log "dry-run: destructive restore was not performed"
    exit 0
fi

# shellcheck source=ops/restore-engine.lib.sh
source "$STACK_DIR/ops/restore-engine.lib.sh"
avelren_restore_engine "$DUMP" "$TARGET" "$STACK_DIR" "$COMPOSE_FILE" "$COMPOSE_PROJECT" "$DB_SERVICE"
