#!/usr/bin/env bash
# Production-source target refusal using only two newly owned fixture clusters.
set -euo pipefail
umask 077

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TOKEN=$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')
[[ "$TOKEN" =~ ^[0-9a-f]{32}$ ]] || exit 1
FIRST="avelren-production-test-${TOKEN}-first"
SECOND="avelren-production-test-${TOKEN}-second"
DB_NAME="avelren_case_${TOKEN}_test"
COMMIT=$(git -C "$ROOT" rev-parse HEAD)
ENV_FILE=$(mktemp)
ROOT_FOR_COMPOSE=$ROOT
ENV_FILE_FOR_COMPOSE=$ENV_FILE
if command -v cygpath >/dev/null 2>&1; then
    ROOT_FOR_COMPOSE=$(cygpath -w "$ROOT")
    ENV_FILE_FOR_COMPOSE=$(cygpath -w "$ENV_FILE")
fi
readonly ROOT TOKEN FIRST SECOND DB_NAME COMMIT ENV_FILE ROOT_FOR_COMPOSE ENV_FILE_FOR_COMPOSE

compose() {
    local project=$1
    shift
    MSYS_NO_PATHCONV=1 docker compose --env-file "$ENV_FILE_FOR_COMPOSE" -p "$project" \
        -f "$ROOT_FOR_COMPOSE/ops/compose.database-test.yml" "$@"
}

owned_container() {
    local id=$1 project=$2 name labels
    name=$(docker inspect --format '{{.Name}}' "$id") || return 1
    labels=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}/{{index .Config.Labels "com.docker.compose.service"}}' "$id") || return 1
    case "$name:$labels" in
        "/${project}-test-db-1:${project}/test-db") ;;
        "/${project}-test-run-"*":${project}/test") ;;
        *) echo "Refusing unowned container: $name" >&2; return 1 ;;
    esac
}

owned_resources() {
    local project=$1 id name label endpoint endpoint_project endpoints
    local containers networks volumes
    containers=$(docker ps -aq --filter "label=com.docker.compose.project=$project") || return 1
    for id in $containers; do owned_container "$id" "$project" || return 1; done
    networks=$(docker network ls -q --filter "label=com.docker.compose.project=$project") || return 1
    for id in $networks; do
        name=$(docker network inspect --format '{{.Name}}' "$id") || return 1
        label=$(docker network inspect --format '{{index .Labels "com.docker.compose.project"}}' "$id") || return 1
        [ "$name:$label" = "${project}_isolated:$project" ] || return 1
        # The first network may also contain the second owned DB. Nothing else may be detached.
        endpoints=$(docker network inspect --format '{{range $id, $value := .Containers}}{{$id}} {{end}}' "$id") || return 1
        for endpoint in $endpoints; do
            endpoint_project=$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project"}}' "$endpoint") || return 1
            case "$endpoint_project" in "$FIRST"|"$SECOND") ;; *) return 1 ;; esac
            owned_container "$endpoint" "$endpoint_project" || return 1
        done
    done
    volumes=$(docker volume ls -q --filter "label=com.docker.compose.project=$project") || return 1
    # This fixture uses tmpfs exclusively; no named volume is owned or removed by the runner.
    [ -z "$volumes" ] || return 1
}

absent_resources() {
    local project=$1 containers networks volumes
    containers=$(docker ps -aq --filter "label=com.docker.compose.project=$project") || return 1
    networks=$(docker network ls -q --filter "label=com.docker.compose.project=$project") || return 1
    volumes=$(docker volume ls -q --filter "label=com.docker.compose.project=$project") || return 1
    [ -z "$containers$networks$volumes" ]
}

# Check collision before installing cleanup: a previous project can never become ours.
for project in "$FIRST" "$SECOND"; do
    absent_resources "$project" || { rm -f -- "$ENV_FILE"; exit 1; }
done

cleanup() {
    local status=$? project
    trap - EXIT
    for project in "$SECOND" "$FIRST"; do
        if owned_resources "$project"; then
            compose "$project" down --volumes || status=1
        else
            echo "Cleanup refused: resource ownership not verified for $project" >&2
            status=1
        fi
        if absent_resources "$project"; then
            echo "Owned cleanup PASS: $project containers=0 networks=0 volumes=0"
        else
            echo "Owned cleanup FAILED: $project" >&2
            status=1
        fi
    done
    rm -f -- "$ENV_FILE"
    exit "$status"
}
trap cleanup EXIT

echo "Owned two-cluster rehearsal: $FIRST $SECOND database=$DB_NAME source=$COMMIT"
compose "$FIRST" build test
compose "$FIRST" run --rm --no-deps -T test python ops/verify-python-container-security.py </dev/null
for project in "$FIRST" "$SECOND"; do
    compose "$project" up -d --wait test-db
    owned_resources "$project"
    compose "$project" exec -T \
        -e AVELREN_TEST_DB=1 -e "AVELREN_DB_NAME=$DB_NAME" \
        -e AVELREN_ADMIN_DSN=postgresql://avelren_admin:ci-only@127.0.0.1:5432/postgres \
        -e AVELREN_ADMIN_PASSWORD=ci-only -e AVELREN_MIGRATOR_PASSWORD=ci-only \
        -e AVELREN_BACKUP_PASSWORD=ci-only -e AVELREN_COLLECTOR_PASSWORD=ci-only \
        -e AVELREN_NOTIFIER_PASSWORD=ci-only -e AVELREN_WATCHDOG_PASSWORD=ci-only \
        -e AVELREN_API_PASSWORD=ci-only \
        test-db bash /workspace/ops/postgres-bootstrap.sh fresh </dev/null
done
SECOND_ID=$(compose "$SECOND" ps -q test-db)
[ -n "$SECOND_ID" ]
owned_container "$SECOND_ID" "$SECOND"
owned_resources "$FIRST"
owned_resources "$SECOND"
docker network connect --alias second-test-db "${FIRST}_isolated" "$SECOND_ID"
for host in test-db second-test-db; do
    compose "$FIRST" run --rm --no-deps -T \
        -e "DATABASE_URL=postgresql://avelren_migrator:ci-only@$host:5432/$DB_NAME" \
        test python -m avelren.migrate db/migrations </dev/null
done
compose "$FIRST" run --rm --no-deps -T \
    -e AVELREN_PRODUCTION_REHEARSAL=1 \
    -e "AVELREN_PRODUCTION_REHEARSAL_NAME=$DB_NAME" \
    -e "AVELREN_PRODUCTION_REHEARSAL_COMMIT=$COMMIT" \
    test python -m pytest -c services/backend/pytest.ini \
    services/backend/tests/rehearsal/test_adoption_two_cluster.py -q -p no:cacheprovider </dev/null
