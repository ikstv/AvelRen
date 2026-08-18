"""Startup schema gate (issue #88).

A gate never seen red is not a gate. So most tests here prove REFUSAL, not
passing: they feed in a too-low version, an empty ledger, and an invalid format,
and require an exception. There is only one green run against a real test DB here
— it proves the wire is actually connected (and that the grant from migration 010
is in place).
"""

import asyncio
import os

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from avelren.schema_gate import (
    SchemaTooOldError,
    _version_ordinal,
    assert_schema_at_least,
    check_recorded_version,
    highest_recorded,
)

DSN = os.environ["DATABASE_URL"]

# A pin of the current requirement. The value is DERIVED (from the
# version-annotated schema_verify contract), so this test does not duplicate the
# logic — it makes a change to it visible in review. A migration that introduces a
# new object into the contract is obligated to change this line along with itself;
# a migration without new objects (like 010, grants only) is not obligated and
# must not.
EXPECTED_REQUIREMENT = "009_observability"


def _run(coro):
    return asyncio.run(coro)


# --- the requirement is derived, not invented -------------------------------


def test_requirement_matches_pinned_value():
    from avelren.schema_gate import required_schema_version

    assert required_schema_version() == EXPECTED_REQUIREMENT


def test_requirement_ignores_grant_only_migrations():
    """010 introduces no contract object, so it does not raise the requirement.

    Otherwise the service would refuse to start over an unapplied ACL layer —
    exactly the state prod is in between 3B.2 and 3D."""
    from avelren.schema_gate import required_schema_version

    assert _version_ordinal(required_schema_version()) < _version_ordinal("010_x")


# --- version ordering: the 009 -> 010 trap ----------------------------------


def test_ordinal_is_numeric_not_lexicographic():
    assert _version_ordinal("010_least_privilege") > _version_ordinal("009_observability")
    assert _version_ordinal("100_future") > _version_ordinal("099_past")


def test_ordinal_rejects_malformed_version():
    with pytest.raises(ValueError):
        _version_ordinal("draft_something")


# --- the highest version is taken numerically, not textually ----------------


def test_highest_recorded_is_numeric_not_textual():
    """This is exactly where a silent bug would hide if relying on SQL max(version)."""
    assert highest_recorded(["009_observability", "010_least_privilege"]) == "010_least_privilege"


def test_highest_recorded_survives_mixed_padding():
    """A textual max would return `009_x` here — i.e. older than the actual one."""
    assert highest_recorded(["009_x", "0010_y"]) == "0010_y"


def test_highest_recorded_on_empty_ledger_is_none():
    assert highest_recorded([]) is None


# --- FALSIFICATION: the gate must refuse ------------------------------------


def test_older_schema_is_refused():
    with pytest.raises(SchemaTooOldError) as excinfo:
        check_recorded_version("008_notification_cancels")
    assert "008_notification_cancels" in str(excinfo.value)
    assert EXPECTED_REQUIREMENT in str(excinfo.value)


def test_empty_ledger_is_refused_not_treated_as_fresh():
    """An empty ledger is a schema with no migration at all, not "new DB, ok"."""
    with pytest.raises(SchemaTooOldError):
        check_recorded_version(None)


def test_exact_requirement_passes():
    check_recorded_version(EXPECTED_REQUIREMENT)


def test_newer_schema_passes():
    check_recorded_version("010_postgresql_least_privilege")


# --- the wire is actually connected -----------------------------------------


def test_gate_passes_against_real_database():
    """End-to-end: a real pool, a real SELECT, a real grant.

    A failure with 42501 here would mean the role has no SELECT on
    schema_migrations — i.e. that the precondition from migration 010 is not applied."""

    async def run():
        pool = AsyncConnectionPool(
            DSN, min_size=1, max_size=1, open=False, kwargs={"row_factory": dict_row}
        )
        await pool.open(wait=True, timeout=30)
        try:
            await assert_schema_at_least(pool)
        finally:
            await pool.close()

    _run(run())


def test_real_ledger_is_populated_and_older_pin_would_refuse():
    """Two things side by side: the test DB really has applied migrations, and the
    same gate on an artificially lowered version refuses. The name deliberately
    describes exactly what is checked — a test whose name is broader than its
    behavior goes green for the wrong reason."""

    async def run():
        async with await psycopg.AsyncConnection.connect(DSN, autocommit=True) as conn:
            conn.row_factory = dict_row
            row = await (
                await conn.execute("SELECT max(version) AS version FROM schema_migrations")
            ).fetchone()
            return row["version"]

    recorded = _run(run())
    assert recorded is not None, "the test DB must have applied migrations"
    # And now the same check on an artificially "spoiled" result.
    with pytest.raises(SchemaTooOldError):
        check_recorded_version("001_init")
