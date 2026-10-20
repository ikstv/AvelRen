#!/usr/bin/env bash
# Native restore + exact ACK acceptance on an owned disposable pair copy.
set -euo pipefail
umask 077

fail() { echo "$1" >&2; exit "${2:-2}"; }
# Refuse inherited native/production configuration before any Docker action.
for variable in $(compgen -v); do
    case "$variable" in
        DATABASE_URL|POSTGRES_*|AVELREN_COMPOSE_*|AVELREN_ADMIN_*|AVELREN_DB_*|AVELREN_STACK_*|AVELREN_SPOOL_*|AVELREN_VERIFY_*|AVELREN_RESTORE_*|AVELREN_PAIR_*)
            [ -z "${!variable:-}" ] || fail rehearsal_configuration_refused ;;
    esac
done
DIRECTORY= MANIFEST= APP_IMAGE= APP_IMAGE_SELECTED=0 LEGACY_TIMESCALE_OWNER=
while [ "$#" -gt 0 ]; do
    case "$1" in
        --directory) [ "$#" -ge 2 ] || fail rehearsal_arguments_invalid; DIRECTORY=$2; shift 2 ;;
        --manifest) [ "$#" -ge 2 ] || fail rehearsal_arguments_invalid; MANIFEST=$2; shift 2 ;;
        --app-image) [ "$#" -ge 2 ] || fail rehearsal_arguments_invalid; APP_IMAGE=$2; APP_IMAGE_SELECTED=1; shift 2 ;;
        --legacy-timescale-owner)
            [ "$#" -ge 2 ] && [ "$2" = avelren ] && [ -z "$LEGACY_TIMESCALE_OWNER" ] \
                || fail rehearsal_arguments_invalid
            LEGACY_TIMESCALE_OWNER=avelren; shift 2 ;;
        *) fail rehearsal_arguments_invalid ;;
    esac
done
[ -d "$DIRECTORY" ] || fail pair_incomplete
[[ "$MANIFEST" =~ ^avelren-[0-9]{8}-[0-9]{6}\.pair\.json$ ]] || fail manifest_name_invalid
if [ "$APP_IMAGE_SELECTED" = 1 ]; then
    [[ "$APP_IMAGE" =~ ^sha256:[0-9a-f]{64}$ ]] || fail rehearsal_image_invalid
    image_identity=$(docker image inspect "$APP_IMAGE" --format '{{.Id}} {{.Os}} {{.Architecture}}' 2>/dev/null) || fail rehearsal_image_unavailable
    [ "$image_identity" = "$APP_IMAGE linux amd64" ] || fail rehearsal_image_identity_mismatch
else
    APP_IMAGE=avelren-app@sha256:9d32a0d54ff9711b54a082f39074e21ba456775b078caf01a293b95109674735
fi
ROOT=$(cd "$(dirname "$0")/.." && pwd)
DIRECTORY=$(cd "$DIRECTORY" && pwd)
WORK=$(mktemp -d "${TMPDIR:-/tmp}/avelren-paired-restore.XXXXXXXX")
PROJECT="avelren-paired-restore-${RANDOM}-${RANDOM}-$$"
readonly ROOT DIRECTORY WORK PROJECT MANIFEST
COMPOSE_STARTED=0
native_path() { if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else printf '%s\n' "$1"; fi; }
export AVELREN_PAIR_ROOT=$(native_path "$ROOT") AVELREN_PAIR_WORK=$(native_path "$WORK")
export AVELREN_PAIR_UID=$(id -u) AVELREN_PAIR_GID=$(id -g)
export AVELREN_PAIR_APP_IMAGE=$APP_IMAGE
COMPOSE_FILE=$(native_path "$ROOT/ops/compose.paired-restore-test.yml")
COMPOSE_ENV=$(native_path "$WORK/compose.env")
COMPOSE_DIR=$(native_path "$WORK")
printf '%s\n' 'AVELREN_COMPOSE_ENV_GUARD=isolated' >"$WORK/compose.env"
readonly APP_IMAGE COMPOSE_FILE COMPOSE_ENV COMPOSE_DIR
compose() {
    MSYS_NO_PATHCONV=1 docker compose --project-directory "$COMPOSE_DIR" \
        --env-file "$COMPOSE_ENV" -f "$COMPOSE_FILE" -p "$PROJECT" "$@"
}
cleanup() {
    local status=$?
    trap - EXIT HUP INT TERM
    if [ "$COMPOSE_STARTED" = 1 ]; then
        if ! compose down --volumes --remove-orphans >/dev/null; then
            echo rehearsal_cleanup_unproven >&2
            # Keep the exact private project journal and original diagnostics.
            [ "$status" != 0 ] || status=1
            exit "$status"
        fi
    fi
    # WORK is the resolved, generated private directory, never a caller argument.
    case "$WORK" in "${TMPDIR:-/tmp}"/avelren-paired-restore.*) rm -rf -- "$WORK" ;; *) status=1 ;; esac
    exit "$status"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

RECEIPT_PYTHON=python3
if command -v cygpath >/dev/null 2>&1; then RECEIPT_PYTHON=python; fi
# Private journal precedes any potentially partial Compose startup. It lets
# the owning fixture recover siblings if this shell is interrupted or down fails.
"$RECEIPT_PYTHON" -c 'import json,os,sys,tempfile;from pathlib import Path
p=Path(sys.argv[1]);fd,tmp=tempfile.mkstemp(prefix=".project-",dir=p.parent)
with os.fdopen(fd,"w") as f:
 json.dump(dict(format_version=1,project=sys.argv[2],compose_file=sys.argv[3],working_dir=sys.argv[4],env_file=sys.argv[5],app_image=sys.argv[6]),f);f.flush();os.fsync(f.fileno())
os.replace(tmp,p)
if os.name=="posix":
 d=os.open(p.parent,os.O_RDONLY);os.fsync(d);os.close(d)' \
  "$(native_path "$WORK/project.json")" "$PROJECT" "$COMPOSE_FILE" "$COMPOSE_DIR" "$COMPOSE_ENV" "$APP_IMAGE"

# All pair/hash/gzip/schema checks finish before a database is even created.
MSYS_NO_PATHCONV=1 docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges \
    --user "$AVELREN_PAIR_UID:$AVELREN_PAIR_GID" -e PYTHONPATH=/workspace/services/backend/src \
    -v "$AVELREN_PAIR_ROOT:/workspace:ro" -v "$(native_path "$DIRECTORY"):/pair-source:ro" \
    -v "$AVELREN_PAIR_WORK:/evidence" -w /workspace "$APP_IMAGE" \
    python ops/paired-restore-acceptance.py prepare --directory /pair-source \
    --manifest "$MANIFEST" --work /evidence/pair
COMPOSE_STARTED=1
compose up -d --wait db
compose exec -T -e AVELREN_TEST_DB=1 -e AVELREN_DB_NAME=avelren_pair_roles_test \
    -e AVELREN_ADMIN_DSN=postgresql://avelren_admin:ci-only@127.0.0.1:5432/postgres \
    -e AVELREN_ADMIN_PASSWORD=ci-only -e AVELREN_MIGRATOR_PASSWORD=ci-only \
    -e AVELREN_BACKUP_PASSWORD=ci-only -e AVELREN_COLLECTOR_PASSWORD=ci-only \
    -e AVELREN_NOTIFIER_PASSWORD=ci-only -e AVELREN_WATCHDOG_PASSWORD=ci-only \
    -e AVELREN_API_PASSWORD=ci-only db bash /workspace/ops/postgres-bootstrap.sh fresh \
    >"$WORK/native-bootstrap.log" 2>&1 || fail native_role_bootstrap_failed 1
# Payload compatibility remains tied to the verified pair. An explicit operator
# observation of legacy Timescale job ownership may independently require this
# restricted role in the fresh disposable cluster, even for a modern writer.
# Never create it through the general restore engine or in a caller-selected DB.
profile=$("$RECEIPT_PYTHON" "$ROOT/ops/paired-restore-acceptance.py" profile \
    --manifest "$(native_path "$WORK/pair/pair.json")") || fail pair_profile_invalid 1
case "$profile" in
    legacy_pre_status) LEGACY_TIMESCALE_OWNER=avelren ;;
    modern_strict) ;;
    *) fail pair_profile_invalid 1 ;;
esac
if [ "$LEGACY_TIMESCALE_OWNER" = avelren ]; then
    compose exec -T -e PGPASSWORD=ci-only \
        -e PGOPTIONS='-c avelren.paired_rehearsal=1' db \
        psql -X -v ON_ERROR_STOP=1 -h 127.0.0.1 -U avelren_admin -d postgres \
        -f /workspace/ops/paired-restore-legacy-role.sql \
        >"$WORK/legacy-role.log" 2>&1 || fail legacy_role_placeholder_failed 1
fi
export AVELREN_STACK_DIR=$ROOT AVELREN_COMPOSE_FILE=$COMPOSE_FILE
export AVELREN_COMPOSE_PROJECT=$PROJECT AVELREN_COMPOSE_PROJECT_DIR=$COMPOSE_DIR
export AVELREN_COMPOSE_ENV_FILE=$COMPOSE_ENV AVELREN_COMPOSE_ENV_GUARD=isolated
export AVELREN_ADMIN_PASSWORD=ci-only
bash "$ROOT/ops/restore.sh" "$WORK/pair/${MANIFEST%.pair.json}.sql.gz" --target restore_test \
    >"$WORK/native-restore.log" 2>&1 || fail native_restore_failed 1
echo native_restore_hooks_and_ownership_ok
export AVELREN_VERIFY_SCHEMA_SERVICE=test AVELREN_VERIFY_API_SERVICE=test
export AVELREN_VERIFY_MIGRATIONS_DIR=db/migrations
export AVELREN_VERIFY_MIGRATOR_DSN=postgresql://avelren_migrator:ci-only@db:5432/restore_test
export AVELREN_VERIFY_API_DSN=postgresql://avelren_api:ci-only@db:5432/restore_test
MSYS_NO_PATHCONV=1 bash "$ROOT/ops/restore-verify.sh" restore_test \
    >"$WORK/native-verify.log" 2>&1 || fail native_schema_api_verification_failed 1
echo native_schema_api_verification_ok
compose run --rm --no-deps -T -e AVELREN_PAIRED_REHEARSAL=1 \
    -e DATABASE_URL=postgresql://avelren_collector:ci-only@db:5432/restore_test \
    test python ops/paired-restore-acceptance.py replay --work /evidence/pair \
    >"$WORK/replay.stdout" 2>"$WORK/replay.stderr" || fail native_replay_failed 1
# Native replay can catch a derived-phase failure and still succeed. Both output
# streams stay private; a separate stdlib reader emits only validated integer evidence.
"$RECEIPT_PYTHON" "$ROOT/ops/paired-restore-acceptance.py" receipt \
    --source "$(native_path "$WORK/replay.stdout")" \
    --manifest "$(native_path "$WORK/pair/pair.json")" \
    >"$WORK/replay.safe.json" 2>"$WORK/receipt.stderr" || fail native_replay_receipt_invalid 1
cat "$WORK/replay.safe.json"
echo paired_restore_rehearsal_ok
