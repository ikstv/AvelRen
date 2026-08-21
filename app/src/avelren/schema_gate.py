"""Fail-closed schema-version check at service startup (issue #88).

WHY THIS EXISTS. Until now, agreement between the schema and the code was
guaranteed only by the `migrate` service, which runs before every start. That
works, but it rests on HOW THE SERVICE IS LAUNCHED: bring a service up with a
different command and no process checks which schema it runs against anymore.
After Gate 11 3B.2 this fragility became tangible: `avelren_migrator` gained
full privileges, so a stray `docker compose up -d` no longer fails loudly but
silently applies and stamps the next migration out of order.

The check here moves fail-closed INSIDE the application — where it cannot be
bypassed by the way the service is launched. That is exactly what opens the way
to put `migrate` back behind a profile (see the migrate comment in
docker-compose.yml).

WHAT IS COMPARED. Not "the last migration in the directory" — runtime containers
do not see the migrations directory. What is compared is the highest version
RECORDED in `schema_migrations` against the highest version the physical code
contract requires.

WHY THE REQUIREMENT IS DERIVED, NOT A CONSTANT. A hand-set constant goes stale
silently: someone adds a migration, forgets to bump the number, and the gate
lets through a schema the code is missing. So the requirement is derived from
the version-annotated `schema_verify` contract, which has to be updated together
with the schema anyway. One place to forget instead of two.

A consequence worth understanding: migrations that do NOT introduce new objects
(for example `010_postgresql_least_privilege` — grants only) do not raise the
requirement. This is deliberate: the code does not structurally rely on them,
and a service must not refuse to start over an unapplied ACL layer.
"""

import logging

from psycopg.rows import tuple_row
from psycopg_pool import AsyncConnectionPool

from . import schema_verify

log = logging.getLogger("avelren.schema_gate")


class SchemaTooOldError(RuntimeError):
    """The DB schema is older than the one this service's code requires."""


def _version_ordinal(version: str) -> int:
    """`009_observability` -> 9. Lexicographic comparison will not do here:
    it falls apart on the 009 -> 010 -> 100 transition while pretending to work."""
    prefix = version.split("_", 1)[0]
    if not prefix.isdigit():
        raise ValueError(f"migration version without a numeric prefix: {version!r}")
    return int(prefix)


def required_schema_version() -> str:
    """The highest version that introduces an object the physical code contract needs."""
    versions = {
        since
        for group in (
            schema_verify._TABLES_V,
            schema_verify._COLUMNS_V,
            schema_verify._UNIQUE_PARTIAL_INDEXES_V,
            schema_verify._INDEXES_V,
            schema_verify._CONSTRAINTS_V,
            schema_verify._HYPERTABLES_V,
            schema_verify._CONTINUOUS_AGGREGATES_V,
        )
        for since in (entry[0] for entry in group)
        if since is not None
    }
    if not versions:
        raise RuntimeError("schema contract is empty — the requirement cannot be derived")
    return max(versions, key=_version_ordinal)


def highest_recorded(versions: list[str]) -> str | None:
    """The highest version by NUMERIC order, not textual.

    SQL `max(version)` will not do here: it is textual. For neatly zero-padded
    001…010 it happens to coincide with the numeric order — and that is exactly
    why it is dangerous: it looks like it works and breaks silently. A single
    version with different padding (`0010_x` next to `009_x`) is enough for the
    textual max to return the older one, so the gate would refuse a perfectly
    fresh schema."""
    if not versions:
        return None
    return max(versions, key=_version_ordinal)


def check_recorded_version(recorded: str | None) -> None:
    """The pure part of the gate: raise if the recorded version is too low.

    `recorded is None` means an empty migration journal — this is NOT "a new
    database, all good", but a schema with no migration applied at all.
    Fail-closed."""
    required = required_schema_version()
    if recorded is None:
        raise SchemaTooOldError(
            f"migration journal is empty; the code requires at least {required}"
        )
    if _version_ordinal(recorded) < _version_ordinal(required):
        raise SchemaTooOldError(
            f"DB schema at {recorded}; the code requires at least {required}"
        )


async def assert_schema_at_least(pool: AsyncConnectionPool) -> None:
    """Called right after the pool opens, before any useful work.

    Any query error (no table, 42501 from a missing grant) is a refusal too: we
    cannot prove agreement, so we do not run. A silent pass here would be worse
    than crashing."""
    # tuple_row is set explicitly: otherwise the row shape would depend on the
    # pool's row_factory, and the gate would silently break in a process
    # configured differently.
    async with pool.connection() as conn:
        cursor = conn.cursor(row_factory=tuple_row)
        await cursor.execute("SELECT version FROM schema_migrations")
        rows = await cursor.fetchall()
    recorded = highest_recorded([row[0] for row in rows])
    check_recorded_version(recorded)
    log.info("schema meets startup requirement: %s", recorded)
