#!/usr/bin/env bash
set -euo pipefail
umask 077

ROOT=$(cd "$(dirname "$0")/.." && pwd)
WORK=$(mktemp -d)
readonly ROOT WORK

cleanup() {
    local status=$?
    trap - EXIT
    rm -rf "$WORK"
    exit "$status"
}
trap cleanup EXIT

fail() {
    echo "postgres adoption contract failed: $*" >&2
    exit 1
}

# shellcheck source=deploy/postgres-ownership.lib.sh
source "$ROOT/deploy/postgres-ownership.lib.sh"

make_fixture() {
    local dir=$1 variant=${2:-canonical}
    mkdir -p "$dir"

    cat >"$dir/database.tsv" <<'EOF'
object	database	avelren_adoption_test	-	avelren_adoption_test	database	avelren	-	-	-	-	-	application	"avelren_adoption_test"
EOF
    cat >"$dir/schema.tsv" <<'EOF'
object	schema	avelren_adoption_test	public	public	schema	avelren	root	-	-	-	-	application	"public"
EOF
    cat >"$dir/extension.tsv" <<'EOF'
object	extension	avelren_adoption_test	-	timescaledb	extension	avelren	-	-	-	-	-	timescale	"timescaledb"
EOF
    cat >"$dir/relations.tsv" <<'EOF'
object	relation	avelren_adoption_test	public	alerts	r	avelren	root:public.alerts	-	-	-	-	application	"public"."alerts"
object	relation	avelren_adoption_test	public	checkpoints	r	avelren	root:public.checkpoints	-	-	-	-	application	"public"."checkpoints"
object	relation	avelren_adoption_test	public	collector_runs	r	avelren	root:public.collector_runs	-	-	-	-	application	"public"."collector_runs"
object	relation	avelren_adoption_test	public	countries	r	avelren	root:public.countries	-	-	-	-	application	"public"."countries"
object	relation	avelren_adoption_test	public	devices	r	avelren	root:public.devices	-	-	-	-	application	"public"."devices"
object	relation	avelren_adoption_test	public	eta_alerts	r	avelren	root:public.eta_alerts	-	-	-	-	application	"public"."eta_alerts"
object	relation	avelren_adoption_test	public	eta_targets	r	avelren	root:public.eta_targets	-	-	-	-	application	"public"."eta_targets"
object	relation	avelren_adoption_test	public	health_alerts	r	avelren	root:public.health_alerts	-	-	-	-	application	"public"."health_alerts"
object	relation	avelren_adoption_test	public	notification_cancels	r	avelren	root:public.notification_cancels	-	-	-	-	application	"public"."notification_cancels"
object	relation	avelren_adoption_test	public	observations	r	avelren	root:public.observations	-	-	-	-	application	"public"."observations"
object	relation	avelren_adoption_test	public	observations_hourly	v	avelren	root:public.observations_hourly	-	-	-	-	application	"public"."observations_hourly"
object	relation	avelren_adoption_test	public	schema_migrations	r	avelren	root:public.schema_migrations	-	-	-	-	application	"public"."schema_migrations"
object	relation	avelren_adoption_test	public	subscription_state	r	avelren	root:public.subscription_state	-	-	-	-	application	"public"."subscription_state"
object	relation	avelren_adoption_test	public	subscriptions	r	avelren	root:public.subscriptions	-	-	-	-	application	"public"."subscriptions"
EOF
    cat >"$dir/sequences.tsv" <<'EOF'
object	relation	avelren_adoption_test	public	alerts_id_seq	S	avelren	root:public.alerts_id_seq	-	-	-	-	application	"public"."alerts_id_seq"
object	relation	avelren_adoption_test	public	eta_alerts_id_seq	S	avelren	root:public.eta_alerts_id_seq	-	-	-	-	application	"public"."eta_alerts_id_seq"
object	relation	avelren_adoption_test	public	eta_targets_id_seq	S	avelren	root:public.eta_targets_id_seq	-	-	-	-	application	"public"."eta_targets_id_seq"
object	relation	avelren_adoption_test	public	health_alerts_id_seq	S	avelren	root:public.health_alerts_id_seq	-	-	-	-	application	"public"."health_alerts_id_seq"
object	relation	avelren_adoption_test	public	notification_cancels_id_seq	S	avelren	root:public.notification_cancels_id_seq	-	-	-	-	application	"public"."notification_cancels_id_seq"
object	relation	avelren_adoption_test	public	subscriptions_id_seq	S	avelren	root:public.subscriptions_id_seq	-	-	-	-	application	"public"."subscriptions_id_seq"
EOF
    cat >"$dir/routines.tsv" <<'EOF'
object	function	avelren_adoption_test	_timescaledb_functions	policy_compression_execute	f	avelren	extension_member	-	-	-	-	timescale	"_timescaledb_functions"."policy_compression_execute"(integer,integer,anyelement,integer,boolean,boolean)
object	type	avelren_adoption_test	_timescaledb_internal	compressed_data	b	avelren	timescale:type:_timescaledb_internal.compressed_data	-	-	-	-	timescale	"_timescaledb_internal"."compressed_data"
EOF
    cat >"$dir/timescale.tsv" <<'EOF'
object	timescale_binding	avelren_adoption_test	public	observations	hypertable	avelren	-	-	-	-	-	timescale	"public"."observations"
object	timescale_binding	avelren_adoption_test	public	observations_hourly	continuous_aggregate	avelren	-	-	-	-	-	timescale	"public"."observations_hourly"
object	relation	avelren_adoption_test	_timescaledb_internal	_hyper_1_1_chunk	r	avelren	timescale:chunk_catalog:public.observations	-	-	-	-	timescale	"_timescaledb_internal"."_hyper_1_1_chunk"
EOF
    cat >"$dir/system.tsv" <<'EOF'
object	relation	avelren_adoption_test	pg_catalog	pg_class	r	postgres	-	-	-	-	-	system	"pg_catalog"."pg_class"
EOF
    cat >"$dir/acl.tsv" <<'EOF'
acl	relation	avelren_adoption_test	public	devices	r	avelren	object	avelren	avelren_api	SELECT	f	application	"public"."devices"
acl	relation	avelren_adoption_test	public	devices	r	avelren	fcm_token	avelren	avelren_notifier	SELECT	f	application	"public"."devices"
acl	schema	avelren_adoption_test	public	public	schema	avelren	object	avelren	PUBLIC	USAGE	f	application	"public"
EOF
    cat >"$dir/shared.tsv" <<'EOF'
object	ownership	16384	1262	16384	0	avelren	target_admin	-	-	-	-	application	16384:1262:16384:0
EOF

    case "$variant" in
        canonical) ;;
        extra-relation)
            printf '%s\n' 'object	relation	avelren_adoption_test	public	unexpected_relation	r	avelren	root:public.unexpected_relation	-	-	-	-	application	"public"."unexpected_relation"' >>"$dir/relations.tsv"
            ;;
        missing-relation)
            grep -v $'\tpublic\talerts\tr\t' "$dir/relations.tsv" >"$dir/relations.tmp"
            mv "$dir/relations.tmp" "$dir/relations.tsv"
            ;;
        extra-extension)
            printf '%s\n' 'object	extension	avelren_adoption_test	-	postgis	extension	avelren	-	-	-	-	-	extension	"postgis"' >>"$dir/extension.tsv"
            ;;
        extra-tablespace)
            printf '%s\n' 'object	tablespace	-	-	legacy_space	tablespace	avelren	-	-	-	-	-	shared	"legacy_space"' >>"$dir/shared.tsv"
            ;;
        extra-shared)
            printf '%s\n' 'object	ownership	0	1262	16385	0	avelren	reject	-	-	-	-	shared	0:1262:16385:0' >>"$dir/shared.tsv"
            ;;
        unknown-owner)
            sed 's/\tavelren\t-/\tunexpected_owner\t-/' "$dir/database.tsv" >"$dir/database.tmp"
            mv "$dir/database.tmp" "$dir/database.tsv"
            ;;
        extra-schema)
            printf '%s\n' $'object\tschema\tavelren_adoption_test\tunexpected_schema\tunexpected_schema\tschema\tavelren\t-\t-\t-\t-\t-\tapplication\t"unexpected_schema"' >>"$dir/schema.tsv"
            ;;
        extra-function)
            printf '%s\n' $'object\tfunction\tavelren_adoption_test\tpublic\tunexpected_function\tf\tavelren\troot\t-\t-\t-\t-\tapplication\t"public"."unexpected_function"()' >>"$dir/routines.tsv"
            ;;
        extra-type)
            printf '%s\n' $'object\ttype\tavelren_adoption_test\tpublic\tunexpected_type\te\tavelren\troot:public.unexpected_type\t-\t-\t-\t-\tapplication\t"public"."unexpected_type"' >>"$dir/routines.tsv"
            ;;
        missing-timescale-binding)
            grep -v $'\tpublic\tobservations_hourly\tcontinuous_aggregate\t' "$dir/timescale.tsv" >"$dir/timescale.tmp"
            mv "$dir/timescale.tmp" "$dir/timescale.tsv"
            ;;
        extra-timescale-binding)
            printf '%s\n' $'object\ttimescale_binding\tavelren_adoption_test\tpublic\tunexpected_hypertable\thypertable\tavelren\t-\t-\t-\t-\t-\ttimescale\t"public"."unexpected_hypertable"' >>"$dir/timescale.tsv"
            ;;
        *) fail "unknown fixture variant: $variant" ;;
    esac
}

CANONICAL="$WORK/canonical"
make_fixture "$CANONICAL"
EVIDENCE="$WORK/evidence"
prepare_evidence_dir "$EVIDENCE"
[ "$(stat -c '%a' "$EVIDENCE")" = 700 ] || fail 'evidence directory is not mode 0700'

export AVELREN_CATALOG_FIXTURE_DIR="$CANONICAL"
export AVELREN_TARGET_DB=avelren_adoption_test
capture_manifest ignored "$EVIDENCE/original.tsv"
[ "$(stat -c '%a' "$EVIDENCE/original.tsv")" = 600 ] || fail 'manifest is not mode 0600'
LC_ALL=C sort -c "$EVIDENCE/original.tsv" || fail 'manifest is not deterministic/sorted'
! grep -q $'\tpg_catalog\t' "$EVIDENCE/original.tsv" || fail 'system catalog leaked into application manifest'
grep -q $'\t_timescaledb_internal\t_hyper_1_1_chunk\t' "$EVIDENCE/original.tsv" || fail 'Timescale structural record missing'
grep -q $'\ttimescale_binding\tavelren_adoption_test\tpublic\tobservations\thypertable\t' "$EVIDENCE/original.tsv" || fail 'Timescale hypertable binding missing'
grep -q $'\ttimescale_binding\tavelren_adoption_test\tpublic\tobservations_hourly\tcontinuous_aggregate\t' "$EVIDENCE/original.tsv" || fail 'Timescale continuous aggregate binding missing'
validate_owned_object_allowlist "$EVIDENCE/original.tsv"

build_forward_plan "$EVIDENCE/original.tsv" "$EVIDENCE/forward.sql" "$ROOT/db/migrations/010_postgresql_least_privilege.sql"
build_inverse_plan "$EVIDENCE/original.tsv" "$EVIDENCE/inverse.sql"
[ "$(stat -c '%a' "$EVIDENCE/forward.sql")" = 600 ] || fail 'forward plan is not mode 0600'
[ "$(stat -c '%a' "$EVIDENCE/inverse.sql")" = 600 ] || fail 'inverse plan is not mode 0600'
# Bootstrap-superuser topology (Decision B): the forward plan must NOT use a
# blanket `REASSIGN OWNED BY avelren` (which would sweep the whole cluster the
# bootstrap role owns). Only explicit per-object ownership handoff of the
# canonical application relations to avelren_migrator is allowed.
! grep -q 'REASSIGN OWNED' "$EVIDENCE/forward.sql" || fail 'forward plan must not use blanket REASSIGN OWNED'
grep -q '^ALTER TABLE "public"\."alerts" OWNER TO "avelren_migrator";' "$EVIDENCE/forward.sql" || fail 'forward plan lacks application handoff'
# Inverse likewise reverses only the application relations, per object, with no
# blanket REASSIGN OWNED.
! grep -q 'REASSIGN OWNED' "$EVIDENCE/inverse.sql" || fail 'inverse plan must not use blanket REASSIGN OWNED'
grep -q '^ALTER TABLE "public"\."alerts" OWNER TO "avelren";' "$EVIDENCE/inverse.sql" || fail 'inverse plan lacks explicit application ownership rollback'
grep -q 'GRANT SELECT ON TABLE "public"\."devices" TO "avelren_api"' "$EVIDENCE/inverse.sql" || fail 'inverse plan was not generated from original ACL manifest'

GRANT_OPTION_MANIFEST="$EVIDENCE/grant-option-source.tsv"
cp "$EVIDENCE/original.tsv" "$GRANT_OPTION_MANIFEST"
printf '%s\n' $'acl\trelation\tavelren_adoption_test\tpublic\talerts\tr\tavelren\tobject\tavelren\tavelren_notifier\tSELECT\ttrue\tapplication\t"public"."alerts"' \
    >>"$GRANT_OPTION_MANIFEST"
LC_ALL=C sort -o "$GRANT_OPTION_MANIFEST" "$GRANT_OPTION_MANIFEST"
chmod 600 "$GRANT_OPTION_MANIFEST"
build_inverse_plan "$GRANT_OPTION_MANIFEST" "$EVIDENCE/grant-option-inverse.sql"
grep -q 'GRANT SELECT ON TABLE "public"\."alerts" TO "avelren_notifier" WITH GRANT OPTION;' \
    "$EVIDENCE/grant-option-inverse.sql" || fail 'inverse plan lost source grant option semantics'

QUOTED_DB_MANIFEST="$EVIDENCE/quoted-database.tsv"
awk -F '\t' 'BEGIN { OFS="\t" }
    {
        if ($3 == "avelren_adoption_test") $3 = "avelren_\"test"
        if ($1 == "object" && $2 == "database") {
            $5 = "avelren_\"test"
            $14 = "\"avelren_\"\"test\""
        }
        print
    }
' "$EVIDENCE/original.tsv" >"$QUOTED_DB_MANIFEST"
chmod 600 "$QUOTED_DB_MANIFEST"
AVELREN_TARGET_DB='avelren_"test' validate_owned_object_allowlist "$QUOTED_DB_MANIFEST"
AVELREN_TARGET_DB='avelren_"test' build_inverse_plan \
    "$QUOTED_DB_MANIFEST" "$EVIDENCE/quoted-database-inverse.sql"
grep -Fq 'REVOKE ALL PRIVILEGES ON DATABASE "avelren_""test"' \
    "$EVIDENCE/quoted-database-inverse.sql" || fail 'database identifier was not derived from validated manifest quoting'

first_hash=$(manifest_fingerprint "$EVIDENCE/original.tsv")
capture_manifest ignored "$EVIDENCE/repeated.tsv"
second_hash=$(manifest_fingerprint "$EVIDENCE/repeated.tsv")
[ "$first_hash" = "$second_hash" ] || fail 'manifest fingerprint is not deterministic'

for variant in extra-relation missing-relation extra-extension extra-tablespace extra-shared unknown-owner extra-schema extra-function extra-type missing-timescale-binding extra-timescale-binding; do
    fixture="$WORK/$variant"
    make_fixture "$fixture" "$variant"
    AVELREN_CATALOG_FIXTURE_DIR="$fixture" capture_manifest ignored "$WORK/$variant.tsv"
    if validate_owned_object_allowlist "$WORK/$variant.tsv" >"$WORK/$variant.out" 2>&1; then
        fail "$variant should fail closed"
    fi
done

# The orchestrator must reject catalog surprises before Compose stop or SQL mutation.
BIN="$WORK/bin"
mkdir -p "$BIN"
cat >"$BIN/docker" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$ADOPTION_DOCKER_LOG"
case " $* " in
    *' ps --status running --services '*)
        if [ "${FAKE_UNEXPECTED_SERVICE:-}" = 1 ]; then
            printf '%s\n' db caddy api collector notifier watchdog unexpected-worker
        elif [ "$(cat "$ADOPTION_DOCKER_STATE" 2>/dev/null || printf running)" = stopped ]; then
            printf '%s\n' db
        else
            printf '%s\n' db caddy api collector notifier watchdog
        fi
        ;;
    *' stop '*)
        [ "${FAKE_STOP_FAIL:-}" != 1 ] || exit 1
        printf '%s\n' stopped >"$ADOPTION_DOCKER_STATE"
        ;;
    *' up '*) exit 91 ;;
esac
EOF
cat >"$BIN/psql" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$ADOPTION_PSQL_LOG"
input=$(cat)
if printf '%s\n' "$input" | grep -q 'AVELREN_ADOPTION_FAILPOINT=before_commit'; then
    printf '%s\n' FAILPOINT >>"$ADOPTION_PSQL_LOG"
    printf '%s\n' FIRST_OWNERSHIP_MUTATION_EXECUTED
    exit 1
fi
printf '%s\n' ROUNDTRIP >>"$ADOPTION_PSQL_LOG"
exit 0
EOF
cat >"$BIN/git" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
case " $* " in
    *' rev-parse HEAD '*) printf '%s\n' ebd09d3bea94236a5d2d0683e973cba90d15eb74 ;;
    *' status --porcelain=v1 --untracked-files=all '*)
        [ "${FAKE_GIT_UNTRACKED:-}" != 1 ] || printf '%s\n' '?? deploy/untracked-adoption-hook.sh'
        ;;
    *' diff '*) exit 0 ;;
    *) exit 2 ;;
esac
EOF
chmod +x "$BIN/docker" "$BIN/psql" "$BIN/git"

PREFLIGHT="$WORK/recovery-preflight"
cat >"$PREFLIGHT" <<EOF
status=PASS
backup_recovery=PASS
exact_commit=ebd09d3bea94236a5d2d0683e973cba90d15eb74
EOF
chmod 600 "$PREFLIGHT"

run_orchestrator() {
    local fixture=$1 name=$2
    shift 2
    : >"$WORK/$name.docker.log"
    : >"$WORK/$name.psql.log"
    printf '%s\n' running >"$WORK/$name.docker.state"
    env PATH="$BIN:$PATH" AVELREN_PSQL_BIN="$BIN/psql" AVELREN_DOCKER_BIN="$BIN/docker" \
        ADOPTION_DOCKER_LOG="$WORK/$name.docker.log" ADOPTION_PSQL_LOG="$WORK/$name.psql.log" \
        ADOPTION_DOCKER_STATE="$WORK/$name.docker.state" \
        AVELREN_CATALOG_FIXTURE_DIR="$fixture" AVELREN_TARGET_DB=avelren_adoption_test \
        AVELREN_ADMIN_DSN='postgresql://contract-secret@invalid/avelren_adoption_test' \
        AVELREN_CURRENT_DB_USER=avelren_admin \
        AVELREN_EXPECTED_COMMIT=ebd09d3bea94236a5d2d0683e973cba90d15eb74 \
        AVELREN_GIT_BIN="$BIN/git" \
        AVELREN_RECOVERY_PREFLIGHT_FILE="$PREFLIGHT" AVELREN_EVIDENCE_DIR="$WORK/$name-evidence" \
        AVELREN_TEST_DB=1 AVELREN_ALLOW_DIRTY_TEST=1 AVELREN_ADOPTION_FAILPOINT=before_commit \
        "$@" bash "$ROOT/deploy/postgres-adopt.sh" \
        --confirm-adoption AVELREN-POSTGRES-ADOPTION \
        >"$WORK/$name.out" 2>&1
}

for variant in extra-relation missing-relation extra-extension extra-tablespace extra-shared unknown-owner extra-schema extra-function extra-type missing-timescale-binding extra-timescale-binding; do
    if run_orchestrator "$WORK/$variant" "orchestrator-$variant"; then
        fail "$variant should reject orchestrator"
    fi
    ! grep -q ' stop ' "$WORK/orchestrator-$variant.docker.log" || fail "$variant reached compose stop"
    [ ! -s "$WORK/orchestrator-$variant.psql.log" ] || fail "$variant reached SQL mutation"
done

for gate in no-confirm wrong-commit bad-recovery; do
    case "$gate" in
        no-confirm) args=(--confirm-adoption WRONG) ;;
        wrong-commit) args=(AVELREN_EXPECTED_COMMIT=0000000000000000000000000000000000000000) ;;
        bad-recovery) args=(AVELREN_RECOVERY_PREFLIGHT_FILE="$WORK/missing") ;;
    esac
    if [ "$gate" = no-confirm ]; then
        if env PATH="$BIN:$PATH" AVELREN_TARGET_DB=avelren_adoption_test AVELREN_TEST_DB=1 \
            bash "$ROOT/deploy/postgres-adopt.sh" "${args[@]}" >"$WORK/$gate.out" 2>&1; then
            fail "$gate should reject orchestrator"
        fi
    elif run_orchestrator "$CANONICAL" "$gate" "${args[@]}"; then
        fail "$gate should reject orchestrator"
    fi
done

if run_orchestrator "$CANONICAL" untracked-worktree \
    AVELREN_ALLOW_DIRTY_TEST=0 FAKE_GIT_UNTRACKED=1; then
    fail 'untracked worktree content should fail the exact-commit gate'
fi
! grep -q ' stop ' "$WORK/untracked-worktree.docker.log" || fail 'untracked worktree reached compose stop'
[ ! -s "$WORK/untracked-worktree.psql.log" ] || fail 'untracked worktree reached SQL'

if run_orchestrator "$CANONICAL" before-commit; then
    fail 'before_commit failpoint must return non-zero'
fi
grep -q 'stop caddy api collector notifier watchdog' "$WORK/before-commit.docker.log" || fail 'known clients were not stopped'
grep -q '^ROUNDTRIP$' "$WORK/before-commit.psql.log" || fail 'plans were not validated before mutation'
grep -q '^FAILPOINT$' "$WORK/before-commit.psql.log" || fail 'before_commit transaction was not exercised'
! grep -q ' up ' "$WORK/before-commit.docker.log" || fail 'orchestrator optimistically restarted runtime'
! grep -q 'contract-secret' "$WORK/before-commit.out" "$WORK/before-commit.docker.log" "$WORK/before-commit.psql.log" || fail 'secret leaked to evidence/logs'

if run_orchestrator "$CANONICAL" unexpected-service FAKE_UNEXPECTED_SERVICE=1; then
    fail 'unexpected running service should fail before maintenance'
fi
! grep -q ' stop ' "$WORK/unexpected-service.docker.log" || fail 'unexpected service reached compose stop'
[ ! -s "$WORK/unexpected-service.psql.log" ] || fail 'unexpected service reached SQL mutation'

if run_orchestrator "$CANONICAL" stop-failure FAKE_STOP_FAIL=1; then
    fail 'client stop failure should fail closed'
fi
! grep -q ' up ' "$WORK/stop-failure.docker.log" || fail 'stop failure triggered optimistic restart'

echo 'postgres adoption contract tests: PASS'
