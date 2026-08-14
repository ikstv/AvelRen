#!/usr/bin/env bash
# Production privilege_contracts acceptance gate for Stage 3B.2.
#
# `postgres-adopt.sh --production-adopt` invokes this as its post-commit gate
# runner: `<this> privilege_contracts`. It runs ONLY the introspection-only
# frozen-ACL tests from app/tests/test_db_privileges.py — every one of them
# asserts against has_*_privilege / pg_has_role catalog functions, so the
# acceptance performs zero INSERT/UPDATE/DELETE/DDL and cannot mutate the live
# database even if the adopted ACL is wrong. The negative-DML and positive-commit
# tests in that module are deliberately NOT selected.
#
# Safety contract:
#   * only the exact argument `privilege_contracts` is accepted;
#   * the frozen ACL is verified by CALLING the existing pytest contract, never
#     by copying its expectations here;
#   * per-role DSNs are forwarded by NAME via `docker compose run -e VAR`, so no
#     credential ever appears on a command line, in `ps`, or in logs;
#   * `docker compose run --rm --no-deps -T` — never up/create/recreate/start/
#     stop/restart, so the production `db` and app services are never touched
#     (respects the 2026-08-14 restore-verify recreation incident);
#   * no migrate, no DSN cutover, no schema change;
#   * pytest's exit code is this script's exit code — any failure is non-zero.
set -euo pipefail

GATE=${1:-}
[ "$GATE" = privilege_contracts ] || {
    echo "privilege gate: only 'privilege_contracts' is supported (got '${1:-}')" >&2
    exit 2
}

ROOT=${AVELREN_STACK_DIR:?AVELREN_STACK_DIR is required}
COMPOSE_FILE=${AVELREN_COMPOSE_FILE:-docker-compose.yml}
GATE_COMPOSE_FILE=${AVELREN_PRIVILEGE_GATE_COMPOSE_FILE:-docker-compose.privilege-gate.yml}
COMPOSE_PROJECT=${AVELREN_COMPOSE_PROJECT:?AVELREN_COMPOSE_PROJECT is required}
GATE_SERVICE=${AVELREN_PRIVILEGE_GATE_SERVICE:-privilege-gate}
DOCKER_BIN=${AVELREN_DOCKER_BIN:-docker}

# Per-role DSNs come from the environment adopt.sh already holds. Require them up
# front (fail closed) but forward them by NAME only, never by value on argv.
: "${AVELREN_ADMIN_TOOL_DSN:?admin tool DSN (AVELREN_ADMIN_TOOL_DSN) is required}"
: "${AVELREN_COLLECTOR_DSN:?collector DSN (AVELREN_COLLECTOR_DSN) is required}"
: "${AVELREN_NOTIFIER_DSN:?notifier DSN (AVELREN_NOTIFIER_DSN) is required}"
: "${AVELREN_WATCHDOG_DSN:?watchdog DSN (AVELREN_WATCHDOG_DSN) is required}"
: "${AVELREN_API_DSN:?api DSN (AVELREN_API_DSN) is required}"
: "${AVELREN_BACKUP_DSN:?backup DSN (AVELREN_BACKUP_DSN) is required}"

# Map to the env var names test_db_privileges.py reads. Exported so that
# `compose run -e NAME` forwards the value from this process environment; the
# value never appears as a command-line argument.
export ADMIN_DATABASE_URL="$AVELREN_ADMIN_TOOL_DSN"
export COLLECTOR_DATABASE_URL="$AVELREN_COLLECTOR_DSN"
export NOTIFIER_DATABASE_URL="$AVELREN_NOTIFIER_DSN"
export WATCHDOG_DATABASE_URL="$AVELREN_WATCHDOG_DSN"
export API_DATABASE_URL="$AVELREN_API_DSN"
export BACKUP_DATABASE_URL="$AVELREN_BACKUP_DSN"

cd "$ROOT"

# Introspection-only subset. Each of these asserts purely against
# has_table_privilege / has_sequence_privilege / has_column_privilege /
# has_schema_privilege / has_database_privilege / pg_has_role — no statement in
# any of them executes DML or DDL. The DML-attempting negative tests and the
# positive-commit service-path tests are intentionally excluded so this gate is
# non-mutating by construction.
TESTS=app/tests/test_db_privileges.py

# `--noconftest` is REQUIRED, not an optimisation. app/tests/conftest.py exists to
# protect the destructive suite: its `pytest_configure` aborts before collection
# unless DATABASE_URL is set, AVELREN_TEST_DB=1, AND the database name contains
# "test" or "ci". Production's database is `avelren`, so that guard can never be
# satisfied here — correctly, because it is guarding a suite that runs DELETEs.
#
# Without this flag the gate aborted with `Exit: DATABASE_URL не задано` (rc=3)
# before running a single assertion. That is what failed the 3B.2 production
# attempt on 2026-08-14: the post-commit gate could not run, so a correctly
# committed adoption was rolled back.
#
# Satisfying the guard instead — exporting DATABASE_URL and AVELREN_TEST_DB=1 for
# the production database — would defeat the exact safeguard that stops the
# destructive suite from touching production. So the gate must not load that
# conftest at all. It does not need it: the seven tests selected below are
# introspection-only and self-contained; they build their own connections from
# the per-role *_DATABASE_URL variables via `connect_env()` and use no conftest
# fixture. `app/tests/conftest.py` is the only conftest in the tree, so nothing
# else is lost. Normal pytest runs still load it and are still refused against a
# non-test database.
exec "$DOCKER_BIN" compose \
    -f "$COMPOSE_FILE" -f "$GATE_COMPOSE_FILE" -p "$COMPOSE_PROJECT" \
    run --rm --no-deps -T \
    -e ADMIN_DATABASE_URL -e COLLECTOR_DATABASE_URL -e NOTIFIER_DATABASE_URL \
    -e WATCHDOG_DATABASE_URL -e API_DATABASE_URL -e BACKUP_DATABASE_URL \
    "$GATE_SERVICE" \
    python -m pytest -q -p no:cacheprovider --noconftest \
        "$TESTS::test_role_has_no_elevated_capability" \
        "$TESTS::test_table_privileges_match_frozen_acl" \
        "$TESTS::test_sequence_privileges_match_frozen_acl" \
        "$TESTS::test_device_column_privileges_match_frozen_acl" \
        "$TESTS::test_column_scoped_updates_match_frozen_acl" \
        "$TESTS::test_column_scoped_selects_match_frozen_acl" \
        "$TESTS::test_public_has_no_existing_application_object_privileges"
