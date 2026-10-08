"""Inventory читає поточну 001–016 без запису."""

import psycopg
import pytest

from avelren.adoption_inventory import AdoptionError, capture, encode, fingerprint
from avelren.privilege_gate import SEQUENCES, TABLES


def read_snapshot(database):
    with psycopg.connect(database("admin"), options="-c default_transaction_read_only=on") as conn:
        conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        return capture(conn)


def test_current_inventory_is_stable_and_complete(database):
    before = read_snapshot(database)
    after = read_snapshot(database)
    assert fingerprint(before) == fingerprint(after)
    roots = {row["name"] for row in before.sections["relations"] if row["schema"] == "public"}
    assert roots == set(TABLES) | set(SEQUENCES)
    assert len(before.sections["journal"]) == 16
    assert len([row for row in before.sections["routines"] if not row["extension"]]) == 4
    assert b"ci-only" not in encode(before)


def test_inventory_refuses_writable_connection(database):
    with psycopg.connect(database("admin")) as conn:
        with pytest.raises(AdoptionError, match="read_only_required"):
            capture(conn)
