"""Production target binding against disposable PostgreSQL only."""

from dataclasses import replace

import psycopg
import pytest

from avelren.adoption_inventory import AdoptionError
from avelren.adoption_target import capture_target, verify_target


def test_adoption_target_matches_current_identity(database):
    with psycopg.connect(database("admin"), options="-c default_transaction_read_only=on") as conn:
        binding = capture_target(conn, source_commit="a" * 40, runtime_digest="b" * 64)
        identity = conn.execute(
            "SELECT system_identifier::text, current_database(), oid, session_user "
            "FROM pg_control_system(), pg_database WHERE datname = current_database()"
        ).fetchone()
        assert (
            binding.system_identifier,
            binding.database,
            binding.database_oid,
            binding.session_role,
        ) == identity
        verify_target(conn, binding)


@pytest.mark.parametrize("field", ["database_oid", "system_identifier", "session_role", "database"])
def test_adoption_target_refuses_changed_identity_before_mutation(database, field):
    with psycopg.connect(database("admin")) as conn:
        conn.execute("CREATE TEMP TABLE mutation_guard (value integer)")
        binding = capture_target(conn, source_commit="a" * 40, runtime_digest="b" * 64)
        changed = {
            "database_oid": binding.database_oid + 1,
            "system_identifier": str(int(binding.system_identifier) + 1),
            "session_role": "avelren_migrator",
            "database": "other",
        }[field]
        with pytest.raises(AdoptionError, match="target_mismatch"):
            verify_target(conn, replace(binding, **{field: changed}))
            conn.execute("INSERT INTO mutation_guard VALUES (1)")
        assert conn.execute("SELECT count(*) FROM mutation_guard").fetchone()[0] == 0


def test_adoption_target_denied_identity_read_refuses(database):
    # PostgreSQL grants this function to PUBLIC by default; deny it only in
    # this disposable database so the permission failure is real and explicit.
    with psycopg.connect(database("admin")) as admin:
        admin.execute("REVOKE EXECUTE ON FUNCTION pg_catalog.pg_control_system() FROM PUBLIC")
    with psycopg.connect(database("collector")) as conn:
        with pytest.raises(AdoptionError, match="target_identity_read_failed"):
            capture_target(conn, source_commit="a" * 40, runtime_digest="b" * 64)
