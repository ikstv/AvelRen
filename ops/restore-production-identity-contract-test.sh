#!/usr/bin/env bash
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
STACK="$WORK/stack"
BIN="$WORK/bin"
mkdir -p "$STACK" "$BIN"
touch "$STACK/docker-compose.yml" "$STACK/.env"

cat >"$BIN/docker" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"${FAKE_LOG:?}"
[ "$1" = inspect ] || exit 40
[ "$2" = --format ] || exit 41
case "$*" in
  *com.docker.compose.project*com.docker.compose.service*com.docker.compose.project.working_dir*) ;;
  *) exit 42 ;;
esac
printf '%s\n' "${FAKE_LABELS:?}"
SH
chmod +x "$BIN/docker"

run_gate() {
    local stack_dir=$1 compose_file=$2 project_dir=$3 env_file=$4 project=$5 service=$6
    bash -c 'set -euo pipefail; fake_docker=$8; export FAKE_LOG=$9 FAKE_LABELS=${10}; docker() { "$fake_docker" "$@"; }; source "$1"; avelren_verify_compose_identity "$2" "$3" "$4" "$5" "$6" "$7"' \
        bash "$ROOT/ops/restore-production-identity.lib.sh" \
        "$stack_dir" "$compose_file" "$project_dir" "$env_file" "$project" "$service" \
        "$BIN/docker" "$WORK/calls.log" "${FAKE_LABELS:-avelren|db|$STACK}"
}

: >"$WORK/calls.log"
run_gate "$STACK" "$STACK/docker-compose.yml" "$STACK" "$STACK/.env" avelren db
grep -q '^inspect --format ' "$WORK/calls.log"
if grep -Eq '(^| )(compose|up|down|create|recreate|start|stop|restart)( |$)' "$WORK/calls.log"; then
    cat "$WORK/calls.log" >&2
    echo 'identity gate issued a non-read-only Docker command' >&2
    exit 1
fi

denied() {
    local name=$1
    shift
    : >"$WORK/calls.log"
    if "$@" >"$WORK/$name.out" 2>&1; then
        echo "expected identity denial: $name" >&2
        exit 1
    fi
}

denied wrong-compose run_gate "$STACK" "$WORK/other.yml" "$STACK" "$STACK/.env" avelren db
[ ! -s "$WORK/calls.log" ]
denied wrong-project-dir run_gate "$STACK" "$STACK/docker-compose.yml" "$WORK" "$STACK/.env" avelren db
[ ! -s "$WORK/calls.log" ]
denied wrong-env run_gate "$STACK" "$STACK/docker-compose.yml" "$STACK" "$WORK/other.env" avelren db
[ ! -s "$WORK/calls.log" ]
denied missing-file run_gate "$STACK" "$STACK/docker-compose.yml" "$STACK" "$WORK/missing.env" avelren db
[ ! -s "$WORK/calls.log" ]

FAKE_LABELS="other|db|$STACK" denied project-label run_gate "$STACK" "$STACK/docker-compose.yml" "$STACK" "$STACK/.env" avelren db
FAKE_LABELS="avelren|api|$STACK" denied service-label run_gate "$STACK" "$STACK/docker-compose.yml" "$STACK" "$STACK/.env" avelren db
FAKE_LABELS="avelren|db|$WORK" denied workdir-label run_gate "$STACK" "$STACK/docker-compose.yml" "$STACK" "$STACK/.env" avelren db

if bash "$ROOT/ops/restore-production-identity.lib.sh" >"$WORK/direct.out" 2>&1; then
    echo 'source-only identity gate ran directly' >&2
    exit 1
fi
grep -q 'source-only' "$WORK/direct.out"
grep -Fq '        /opt/avelren \' "$ROOT/ops/restore-production-identity.lib.sh"
grep -Fq '        avelren \' "$ROOT/ops/restore-production-identity.lib.sh"
grep -Fq '        db' "$ROOT/ops/restore-production-identity.lib.sh"

echo 'production Compose identity contract: PASS (7 denials + source-only guard)'
