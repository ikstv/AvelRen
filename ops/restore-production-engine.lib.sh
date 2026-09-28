#!/usr/bin/env bash
# Source-only production wrapper. The target is intentionally not an argument.

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "DENIED: production restore engine is source-only" >&2
    exit 2
fi

_AVELREN_PRODUCTION_ENGINE_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# shellcheck source=ops/restore-engine.lib.sh
source "$_AVELREN_PRODUCTION_ENGINE_DIR/restore-engine.lib.sh"

avelren_restore_production_engine() {
    [ "$#" -eq 5 ] || {
        echo "DENIED: production restore engine requires exactly five arguments" >&2
        return 2
    }
    local dump=$1 stack_dir=$2 compose_file=$3 compose_project=$4 db_service=$5
    _avelren_require_restore_admin || return
    _avelren_restore_engine_primitive "$dump" avelren "$stack_dir" "$compose_file" "$compose_project" "$db_service"
}
