#!/usr/bin/env bash
# Source-only artifact gate shared by future restore orchestrators.

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "DENIED: restore artifact verifier is source-only" >&2
    exit 2
fi

avelren_verify_restore_artifact() {
    local dump=${1:?dump path is required}
    local sidecar=${2:?SHA-256 sidecar path is required}
    local expected_digest expected_name actual_digest ignored
    local -a sidecar_lines

    [ -f "$dump" ] || { echo "DENIED: backup artifact not found" >&2; return 1; }
    [ -f "$sidecar" ] || { echo "DENIED: backup SHA-256 sidecar not found" >&2; return 1; }
    gzip -t -- "$dump" || { echo "DENIED: backup artifact failed gzip integrity validation" >&2; return 1; }

    # Do not pass an untrusted sidecar to `sha256sum --check`: its filename
    # field could make that command read an arbitrary local path.
    mapfile -t sidecar_lines <"$sidecar"
    if [ "${#sidecar_lines[@]}" -ne 1 ] || ! [[ "${sidecar_lines[0]}" =~ ^([[:xdigit:]]{64})\ \ (.+)$ ]]; then
        echo "DENIED: backup SHA-256 sidecar must contain one canonical entry" >&2
        return 1
    fi
    expected_digest=${BASH_REMATCH[1],,}
    expected_name=${BASH_REMATCH[2]}
    if [[ "$expected_name" == */* || "$expected_name" == *\\* || "$expected_name" == *$'\t'* || "$expected_name" == *' '* ]] || [ "$expected_name" != "$(basename -- "$dump")" ]; then
        echo "DENIED: backup SHA-256 sidecar names a different artifact" >&2
        return 1
    fi

    read -r actual_digest ignored < <(sha256sum -- "$dump")
    actual_digest=${actual_digest,,}
    [ "$actual_digest" = "$expected_digest" ] || { echo "DENIED: backup SHA-256 sidecar digest mismatch" >&2; return 1; }
}
