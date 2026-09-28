#!/usr/bin/env bash
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/bin" "$WORK/source/db/migrations"
REAL_PYTHON=$(command -v python3)
printf 'select 1;\n' >"$WORK/source/db/migrations/001_init.sql"
printf 'synthetic dump\n' >"$WORK/dump.sql.gz"
printf 'sidecar is verified by the separately tested artifact gate\n' >"$WORK/dump.sql.gz.sha256"
DUMP_SHA=$(sha256sum "$WORK/dump.sql.gz" | awk '{print $1}')

"$REAL_PYTHON" - "$WORK/evidence.json" "$WORK/source/db/migrations/001_init.sql" "$DUMP_SHA" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

record_path = Path(sys.argv[1])
migration_path = Path(sys.argv[2])
dump_sha = sys.argv[3]
roles = {
    "avelren_admin": {"login": True, "superuser": True},
    "avelren_migrator": {"login": True, "superuser": False},
    "avelren_backup": {"login": True, "superuser": False},
    "avelren_collector": {"login": True, "superuser": False},
    "avelren_notifier": {"login": True, "superuser": False},
    "avelren_watchdog": {"login": True, "superuser": False},
    "avelren_api": {"login": True, "superuser": False},
}
record_path.write_text(json.dumps({
    "target_commit": "a" * 40,
    "recovery_migration_pin": "001_init",
    "database_journal": {"001_init": hashlib.sha256(migration_path.read_bytes()).hexdigest()},
    "role_model": "least-privilege-v1",
    "roles": roles,
    "role_memberships": {role: [] for role in roles},
    "ownership_and_grants_verified": True,
    "backup_sha256": dump_sha,
}), encoding="utf-8")
PY

cat >"$WORK/bin/python3" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [[ " $* " == *'restore-role-pin.py verify '* ]]; then
    printf 'static\n' >>"$PREFLIGHT_LOG"
elif [ "${1:-}" = - ]; then
    printf 'metadata\n' >>"$PREFLIGHT_LOG"
fi
exec "$REAL_PYTHON" "$@"
SH
cat >"$WORK/bin/docker" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
[[ " $* " == *' compose '* ]] || exit 40
[[ " $* " == *' exec -T -e PGPASSWORD -e PGOPTIONS -e AVELREN_EXPECTED_JOURNAL db psql '* ]] || exit 41
[[ " $* " == *' -U avelren_admin '* ]] || exit 42
[[ " $* " == *' -d avelren '* ]] || exit 43
[[ "$*" != *"$SECRET_SENTINEL"* ]] || exit 44
sql=$(cat)
case "$sql" in
  *preflight:database*)
    stage=database
    [[ "$sql" == *current_database*jsonb_object_agg*schema_migrations* ]] || exit 46
    [ -n "${AVELREN_EXPECTED_JOURNAL:-}" ] || exit 47
    ;;
  *preflight:roles-and-grants*)
    stage=roles-and-grants
    [[ "$sql" == *pg_roles*pg_auth_members*has_database_privilege*has_schema_privilege* ]] || {
      echo 'roles SQL contract is incomplete' >&2; exit 48; }
    [[ "$sql" == *owner_name*has_sequence_privilege*has_table_privilege* ]] || {
      echo 'ownership/grants SQL contract is incomplete' >&2; exit 49; }
    ;;
  *preflight:sessions*)
    stage=sessions
    [[ "$sql" == *pg_stat_activity*pg_backend_pid* ]] || exit 50
    ;;
  *) exit 45 ;;
esac
printf '%s\n' "$stage" >>"$PREFLIGHT_LOG"
upper=${stage^^}; upper=${upper//-/_}; var="FAKE_${upper}_OUTPUT"
printf '%b\n' "${!var:-t}"
SH
chmod +x "$WORK/bin/python3" "$WORK/bin/docker"

run_preflight() {
    : >"$WORK/calls.log"
    PATH="$WORK/bin:$PATH" \
      REAL_PYTHON="$REAL_PYTHON" \
      PREFLIGHT_LOG="$WORK/calls.log" \
      SECRET_SENTINEL='admin-contract-secret' \
      AVELREN_ADMIN_PASSWORD='admin-contract-secret' \
      bash -c '
        set -euo pipefail
        source "$1"
        avelren_verify_restore_artifact() {
          printf "artifact\n" >>"$PREFLIGHT_LOG"
          [ "${FAKE_ARTIFACT_FAIL:-0}" != 1 ]
        }
        avelren_verify_production_compose_identity() {
          printf "identity\n" >>"$PREFLIGHT_LOG"
          [ "${FAKE_IDENTITY_FAIL:-0}" != 1 ]
        }
        avelren_verify_production_preflight "$2" "$3" "$4" "$5"
        printf "%s|%s|%s\n" "$AVELREN_VERIFIED_TARGET_COMMIT" "$AVELREN_VERIFIED_MIGRATION_PIN" "$AVELREN_VERIFIED_ARTIFACT_SHA"
      ' bash "$ROOT/ops/restore-production-preflight.lib.sh" \
        "$WORK/dump.sql.gz" "$WORK/dump.sql.gz.sha256" "$WORK/evidence.json" "$WORK/source"
}

output=$(run_preflight)
[ "$output" = "$(printf 'a%.0s' {1..40})|001_init|$DUMP_SHA" ]
expected=$(printf '%s\n' artifact identity static metadata database roles-and-grants sessions)
[ "$(cat "$WORK/calls.log")" = "$expected" ]
! grep -q 'admin-contract-secret' "$WORK/calls.log"

denied_at() {
    local name=$1 expected_log=$2; shift 2
    if ( if (($#)); then export "$@"; fi; run_preflight ) >"$WORK/$name.out" 2>&1; then
        echo "expected preflight denial: $name" >&2
        exit 1
    fi
    [ "$(cat "$WORK/calls.log")" = "$expected_log" ] || {
        echo "unexpected call sequence for $name" >&2
        cat "$WORK/calls.log" >&2
        exit 1
    }
    ! grep -q 'admin-contract-secret' "$WORK/$name.out"
}

denied_at artifact artifact FAKE_ARTIFACT_FAIL=1
denied_at identity "$(printf '%s\n' artifact identity)" FAKE_IDENTITY_FAIL=1

cp "$WORK/evidence.json" "$WORK/evidence.good"
"$REAL_PYTHON" - "$WORK/evidence.json" <<'PY'
import json, sys
path = sys.argv[1]
record = json.load(open(path, encoding="utf-8"))
record["target_commit"] = "INVALID"
json.dump(record, open(path, "w", encoding="utf-8"))
PY
denied_at static "$(printf '%s\n' artifact identity static)"
cp "$WORK/evidence.good" "$WORK/evidence.json"

denied_at database "$(printf '%s\n' artifact identity static metadata database)" \
    FAKE_DATABASE_OUTPUT=f
denied_at journal-mismatch "$(printf '%s\n' artifact identity static metadata database)" \
    FAKE_DATABASE_OUTPUT=f
for roles_case in runtime-superuser unexpected-membership unexpected-owner unexpected-grant; do
    denied_at "$roles_case" "$(printf '%s\n' artifact identity static metadata database roles-and-grants)" \
        FAKE_ROLES_AND_GRANTS_OUTPUT=f
done
denied_at sessions "$expected" FAKE_SESSIONS_OUTPUT=f

command_marker="$WORK/command-was-run"
denied_at hostile-output "$(printf '%s\n' artifact identity static metadata database)" \
    FAKE_DATABASE_OUTPUT="t\n\$(touch $command_marker)"
[ ! -e "$command_marker" ]

: >"$WORK/calls.log"
if PATH="$WORK/bin:$PATH" REAL_PYTHON="$REAL_PYTHON" PREFLIGHT_LOG="$WORK/calls.log" \
    SECRET_SENTINEL=unused AVELREN_ADMIN_PASSWORD= \
    bash -c 'source "$1"; avelren_verify_production_preflight "$2" "$3" "$4" "$5"' \
      bash "$ROOT/ops/restore-production-preflight.lib.sh" \
      "$WORK/dump.sql.gz" "$WORK/dump.sql.gz.sha256" "$WORK/evidence.json" "$WORK/source"; then
    echo "missing admin password was accepted" >&2
    exit 1
fi
[ ! -s "$WORK/calls.log" ]

if bash "$ROOT/ops/restore-production-preflight.lib.sh" >"$WORK/direct.out" 2>&1; then
    echo "source-only production preflight ran directly" >&2
    exit 1
fi
grep -q source-only "$WORK/direct.out"

echo "production preflight contract: PASS"
