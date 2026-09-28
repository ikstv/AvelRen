#!/usr/bin/env bash
# Manual, fail-closed production restore orchestrator.
set -euo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=ops/restore-production-preflight.lib.sh
source "$SCRIPT_DIR/restore-production-preflight.lib.sh"
# shellcheck source=ops/restore-production-engine.lib.sh
source "$SCRIPT_DIR/restore-production-engine.lib.sh"

readonly AVELREN_PRODUCTION_STACK=/opt/avelren
readonly AVELREN_PRODUCTION_COMPOSE=/opt/avelren/docker-compose.yml
readonly AVELREN_PRODUCTION_PROJECT=avelren
readonly AVELREN_PRODUCTION_DB_SERVICE=db
readonly AVELREN_RESTORE_RECEIPT_DIR=/run/avelren-restore
readonly AVELREN_RESTORE_MAINTENANCE_FILE=/var/lib/avelren-telemetry/maintenance.json
readonly AVELREN_EXTERNAL_HEALTH_URL=https://api.bordersignal.pp.ua/api/health

AVELREN_RESTORE_PHASE=preflight
AVELREN_RESTORE_MAINTENANCE_STARTED=false
AVELREN_RESTORE_CADDY_STARTED=false
AVELREN_RESTORE_RECEIPT=
AVELREN_RESTORE_ARTIFACT=
AVELREN_RESTORE_ARTIFACT_STAT=
AVELREN_RESTORE_ARTIFACT_SHA=

avelren_compose() {
    docker compose --project-directory "$AVELREN_PRODUCTION_STACK" \
      --env-file "$AVELREN_PRODUCTION_STACK/.env" \
      -f "$AVELREN_PRODUCTION_COMPOSE" -p "$AVELREN_PRODUCTION_PROJECT" "$@"
}

avelren_confirm_production_restore() {
    local input_fd=${1:?input descriptor is required} answer expected
    expected="RESTORE avelren $(date -u +%F)"
    IFS= read -r -u "$input_fd" answer || return 1
    [ "$answer" = "$expected" ] || {
        echo "DENIED: production restore confirmation did not match" >&2
        return 1
    }
}

avelren_require_production_operator() {
    local input_fd
    [ "$(id -u)" -eq 0 ] || {
        echo "DENIED: production restore must run as root" >&2
        return 77
    }
    exec {input_fd}<>/dev/tty || {
        echo "DENIED: production restore requires an interactive TTY" >&2
        return 77
    }
    [ -t "$input_fd" ] || {
        exec {input_fd}>&-
        echo "DENIED: production restore confirmation input is not a TTY" >&2
        return 77
    }
    printf 'Type RESTORE avelren %s to continue: ' "$(date -u +%F)" >&"$input_fd"
    local status=0
    avelren_confirm_production_restore "$input_fd" || status=$?
    exec {input_fd}>&-
    return "$status"
}

avelren_capture_restore_artifact() {
    local artifact=$1 mode
    [ -f "$artifact" ] && [ ! -L "$artifact" ] && [ -r "$artifact" ] || {
        echo "DENIED: restore artifact must be a readable regular non-symlink file" >&2
        return 1
    }
    [ "$(stat -c %u -- "$artifact")" -eq 0 ] || {
        echo "DENIED: restore artifact must be root-owned" >&2
        return 1
    }
    mode=$(stat -c %a -- "$artifact")
    (( (8#$mode & 022) == 0 )) || {
        echo "DENIED: restore artifact must not be group/world writable" >&2
        return 1
    }
    AVELREN_RESTORE_ARTIFACT=$(realpath -e -- "$artifact")
    AVELREN_RESTORE_ARTIFACT_STAT=$(stat -Lc '%d:%i:%s' -- "$AVELREN_RESTORE_ARTIFACT")
    read -r AVELREN_RESTORE_ARTIFACT_SHA _ < <(sha256sum -- "$AVELREN_RESTORE_ARTIFACT")
    [[ "$AVELREN_RESTORE_ARTIFACT_SHA" =~ ^[0-9a-f]{64}$ ]] || return 1
}

avelren_recheck_restore_artifact() {
    local current_path current_stat current_sha ignored
    current_path=$(realpath -e -- "$AVELREN_RESTORE_ARTIFACT") || {
        echo "DENIED: restore artifact disappeared after preflight" >&2
        return 1
    }
    [ "$current_path" = "$AVELREN_RESTORE_ARTIFACT" ] || {
        echo "DENIED: restore artifact path changed after preflight" >&2
        return 1
    }
    current_stat=$(stat -Lc '%d:%i:%s' -- "$current_path") || return 1
    [ "$current_stat" = "$AVELREN_RESTORE_ARTIFACT_STAT" ] || {
        echo "DENIED: restore artifact identity changed after preflight" >&2
        return 1
    }
    read -r current_sha ignored < <(sha256sum -- "$current_path")
    [ "$current_sha" = "$AVELREN_RESTORE_ARTIFACT_SHA" ] || {
        echo "DENIED: restore artifact digest changed after preflight" >&2
        return 1
    }
}

avelren_create_safety_snapshot() {
    install -d -m 0700 "$AVELREN_RESTORE_RECEIPT_DIR"
    AVELREN_RESTORE_RECEIPT="$AVELREN_RESTORE_RECEIPT_DIR/safety-snapshot.json"
    AVELREN_BACKUP_RECEIPT="$AVELREN_RESTORE_RECEIPT" "$SCRIPT_DIR/backup.sh"
    [ -f "$AVELREN_RESTORE_RECEIPT" ] && [ "$(stat -c %a "$AVELREN_RESTORE_RECEIPT")" = 600 ] || {
        echo "DENIED: verified safety snapshot receipt is unavailable" >&2
        return 1
    }
    python3 - "$AVELREN_RESTORE_RECEIPT" <<'PY'
import json
import re
import sys

with open(sys.argv[1], encoding="utf-8") as source:
    receipt = json.load(source)
if set(receipt) != {"created_at", "remote_artifact", "remote_sidecar", "sha256", "bytes"}:
    raise SystemExit(1)
if not isinstance(receipt["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", receipt["sha256"]):
    raise SystemExit(1)
if not isinstance(receipt["bytes"], int) or isinstance(receipt["bytes"], bool) or receipt["bytes"] <= 0:
    raise SystemExit(1)
PY
}

avelren_publish_restore_maintenance() {
    "$SCRIPT_DIR/maintenance-works.sh" --duration-seconds 21600
    AVELREN_RESTORE_MAINTENANCE_STARTED=true
}

avelren_stop_production_clients() {
    avelren_compose stop caddy
    avelren_compose stop api collector notifier watchdog
}

avelren_stop_caddy_fail_closed() {
    avelren_compose stop caddy >/dev/null 2>&1 || true
}

avelren_verify_post_restore_schema_roles() {
    avelren_verify_production_database_journal
    avelren_verify_production_roles_owners_grants
}

avelren_start_production_clients() {
    AVELREN_RESTORE_RUNTIME_STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    export AVELREN_RESTORE_RUNTIME_STARTED_AT
    avelren_compose up -d --no-deps api collector notifier watchdog
}

avelren_verify_internal_api() {
    avelren_compose exec -T api python - <<'PY'
import json
import urllib.request

with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=15) as response:
    payload = json.load(response)
if payload.get("status") not in {"ok", "stale"}:
    raise SystemExit(1)
PY
}

avelren_wait_for_collector_cycle() {
    local attempt result
    for attempt in $(seq 1 25); do
        result=$(
            PGPASSWORD="$AVELREN_ADMIN_PASSWORD" \
            PGOPTIONS='-c default_transaction_read_only=on' \
            AVELREN_RESTORE_STARTED_AT="$AVELREN_RESTORE_RUNTIME_STARTED_AT" \
            avelren_compose exec -T -e PGPASSWORD -e PGOPTIONS -e AVELREN_RESTORE_STARTED_AT db \
              psql -X -v ON_ERROR_STOP=1 -At -U avelren_admin -d avelren <<'SQL'
\getenv restore_started_at AVELREN_RESTORE_STARTED_AT
SELECT EXISTS (
    SELECT 1 FROM public.collector_runs
    WHERE time >= :'restore_started_at'::timestamptz
      AND http_status BETWEEN 200 AND 299
      AND error IS NULL
      AND derived_processed_at IS NOT NULL
      AND derived_error IS NULL
);
SQL
        ) || return 1
        [ "$result" != t ] || return 0
        [ "$result" = f ] || return 1
        sleep 5
    done
    echo "collector did not complete a successful natural cycle after restore" >&2
    return 1
}

avelren_validate_caddy_config() {
    avelren_compose run --rm --no-deps -T caddy \
      caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
}

avelren_start_caddy() {
    avelren_compose start caddy
    AVELREN_RESTORE_CADDY_STARTED=true
}

avelren_verify_external_health() {
    local response
    response=$(curl --fail --silent --show-error --max-time 20 "$AVELREN_EXTERNAL_HEALTH_URL")
    python3 -c 'import json,sys; raise SystemExit(json.load(sys.stdin).get("status") != "ok")' <<<"$response"
}

avelren_clear_restore_maintenance() {
    rm -f -- "$AVELREN_RESTORE_MAINTENANCE_FILE"
}

avelren_restore_recovery_summary() {
    printf '%s\n' \
      "production restore stopped fail-closed" \
      "phase=$AVELREN_RESTORE_PHASE" \
      "ingress=caddy-stopped" \
      "verified_snapshot_receipt=${AVELREN_RESTORE_RECEIPT:-unavailable}" \
      "runbook=ops/RECOVERY.md#production-restore-failure" >&2
}

avelren_restore_exit_trap() {
    local status=$?
    trap - EXIT HUP INT TERM
    if [ "$status" -ne 0 ] && [ "$AVELREN_RESTORE_MAINTENANCE_STARTED" = true ] && \
       [ "$AVELREN_RESTORE_PHASE" != complete ]; then
        avelren_stop_caddy_fail_closed
        avelren_restore_recovery_summary
    fi
    exit "$status"
}

avelren_restore_usage() {
    echo "usage: $0 --artifact PATH --sidecar PATH --evidence PATH" >&2
    return 64
}

avelren_restore_production_main() {
    local artifact= sidecar= evidence=
    while (($#)); do
        case "$1" in
            --artifact) artifact=${2:-}; shift 2 ;;
            --sidecar) sidecar=${2:-}; shift 2 ;;
            --evidence) evidence=${2:-}; shift 2 ;;
            *) avelren_restore_usage; return ;;
        esac
    done
    [ -n "$artifact" ] && [ -n "$sidecar" ] && [ -n "$evidence" ] || {
        avelren_restore_usage
        return
    }

    trap avelren_restore_exit_trap EXIT
    trap 'exit 129' HUP
    trap 'exit 130' INT
    trap 'exit 143' TERM

    avelren_require_production_operator
    local input mode
    for input in "$sidecar" "$evidence"; do
        [ -f "$input" ] && [ ! -L "$input" ] && [ -r "$input" ] || {
            echo "DENIED: production restore input is not a readable regular non-symlink file" >&2
            return 1
        }
        [ "$(stat -c %u -- "$input")" -eq 0 ] || {
            echo "DENIED: production restore inputs must be root-owned" >&2
            return 1
        }
        mode=$(stat -c %a -- "$input")
        (( (8#$mode & 022) == 0 )) || {
            echo "DENIED: production restore inputs must not be group/world writable" >&2
            return 1
        }
    done
    avelren_capture_restore_artifact "$artifact"
    avelren_verify_production_preflight "$AVELREN_RESTORE_ARTIFACT" "$sidecar" "$evidence" "$AVELREN_PRODUCTION_STACK"
    [ "$AVELREN_VERIFIED_ARTIFACT_SHA" = "$AVELREN_RESTORE_ARTIFACT_SHA" ] || return 1

    avelren_create_safety_snapshot
    AVELREN_RESTORE_PHASE=snapshot_verified
    avelren_publish_restore_maintenance
    AVELREN_RESTORE_PHASE=maintenance
    avelren_stop_production_clients
    avelren_verify_production_quiescent_sessions
    avelren_recheck_restore_artifact
    avelren_restore_production_engine "$AVELREN_RESTORE_ARTIFACT" "$AVELREN_PRODUCTION_STACK" \
      "$AVELREN_PRODUCTION_COMPOSE" "$AVELREN_PRODUCTION_PROJECT" "$AVELREN_PRODUCTION_DB_SERVICE"
    AVELREN_RESTORE_PHASE=restored

    avelren_verify_post_restore_schema_roles
    avelren_start_production_clients
    avelren_verify_internal_api
    avelren_wait_for_collector_cycle
    avelren_validate_caddy_config
    avelren_start_caddy
    avelren_verify_external_health
    AVELREN_RESTORE_PHASE=healthy

    trap '' HUP INT TERM
    avelren_clear_restore_maintenance
    AVELREN_RESTORE_PHASE=complete
    trap - EXIT HUP INT TERM
    printf 'production restore complete: commit=%s migration_pin=%s artifact_sha256=%s\n' \
      "$AVELREN_VERIFIED_TARGET_COMMIT" "$AVELREN_VERIFIED_MIGRATION_PIN" \
      "$AVELREN_VERIFIED_ARTIFACT_SHA"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    avelren_restore_production_main "$@"
fi
