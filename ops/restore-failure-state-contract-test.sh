#!/usr/bin/env bash
# No Docker daemon is used. Model services restarted before a failed API check.
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
for scenario in success stop-failure inspect-failure running missing cleanup-signal; do
    mkdir "$WORK/$scenario"
    for service in caddy api collector notifier watchdog; do
        printf 'running\n' >"$WORK/$scenario/$service"
    done
    set +e
    env FIXTURE="$WORK/$scenario" SCENARIO="$scenario" bash -c '
      source "$1/ops/restore-production.sh"
      services=(caddy api collector notifier watchdog)
      avelren_compose() {
        printf "%s\n" "$*" >>"$FIXTURE/calls"
        case "$1" in
          stop)
            if [ "$SCENARIO" = cleanup-signal ] && [ "$2" = caddy ]; then kill -TERM "$$"; fi
            if [ "$SCENARIO" = stop-failure ] && [ "$2" = api ]; then return 42; fi
            if [ "$SCENARIO" != running ] || [ "$2" != collector ]; then
              printf "exited\n" >"$FIXTURE/$2"
            fi
            ;;
          ps)
            [ "$*" = "ps --all --quiet ${@: -1}" ] || return 43
            service=${@: -1}
            [ "$SCENARIO" != missing ] || [ "$service" != watchdog ] || return 0
            for index in "${!services[@]}"; do
              if [ "${services[$index]}" = "$service" ]; then printf "%064x\n" "$((index+1))"; fi
            done
            ;;
          *) return 44 ;;
        esac
      }
      docker() {
        [ "$1" = inspect ] && [ "$2" = --format ] && [ "$3" = "{{.State.Status}}" ] || return 45
        id=${4: -1}; service=${services[$((id-1))]}
        [ "$SCENARIO" != inspect-failure ] || [ "$service" != notifier ] || return 46
        cat "$FIXTURE/$service"
      }
      AVELREN_RESTORE_PHASE=restored
      AVELREN_RESTORE_MAINTENANCE_STARTED=true
      trap avelren_restore_exit_trap EXIT
      exit 71
    ' bash "$ROOT" >"$WORK/$scenario/output" 2>&1
    status=$?
    set -e
    [ "$status" -eq 71 ] || { cat "$WORK/$scenario/output"; exit 1; }
    for service in caddy api collector notifier watchdog; do
        grep -qx "stop $service" "$WORK/$scenario/calls" || {
            echo "FAIL: $scenario omitted stop $service" >&2; exit 1;
        }
    done
    if [ "$scenario" = success ] || [ "$scenario" = cleanup-signal ]; then
        for service in caddy api collector notifier watchdog; do
            [ "$(cat "$WORK/$scenario/$service")" = exited ]
        done
        grep -q 'failure_state=stopped-verified' "$WORK/$scenario/output"
    else
        grep -q 'failure_state=unverified' "$WORK/$scenario/output"
        ! grep -q 'failure_state=stopped-verified' "$WORK/$scenario/output"
    fi
done
echo 'restore failure-state contracts: 6 passed'
