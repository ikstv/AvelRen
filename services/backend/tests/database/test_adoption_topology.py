"""Ownership roundtrip includes Timescale compressed/CAGG objects and data."""

import psycopg
import pytest
from psycopg import sql

from avelren.adoption_inventory import fingerprint
from avelren.adoption_plan import build_plan
from avelren.postgres_adoption import read_snapshot
from avelren.privilege_gate import SEQUENCES, TABLES


def seed(database):
    with psycopg.connect(database("admin"), autocommit=True) as conn:
        conn.execute("INSERT INTO checkpoints(id,title,for_vehicle_type) VALUES(17,'Synthetic',1)")
        conn.execute(
            "INSERT INTO observations(time,checkpoint_id,wait_time_seconds,vehicles_in_queue,"
            "is_paused,wait_time_status) VALUES(now()-interval '14 days',17,3600,20,"
            "false,'reported'),(now()-interval '13 days',17,7200,40,false,'reported')"
        )
        conn.execute(
            "CALL refresh_continuous_aggregate('observations_hourly',"
            "now()-interval '20 days',now())"
        )
        conn.execute("SELECT compress_chunk(show_chunks('observations'),if_not_compressed=>true)")


def rows(database):
    with psycopg.connect(database("admin")) as conn:
        return (
            conn.execute("SELECT * FROM observations ORDER BY time").fetchall(),
            conn.execute("SELECT * FROM observations_hourly ORDER BY bucket").fetchall(),
            conn.execute("SELECT * FROM schema_migrations ORDER BY version").fetchall(),
        )


@pytest.mark.parametrize("legacy_owners", [False, True])
def test_adoption_compressed_topology_roundtrip(database, legacy_owners):
    seed(database)
    data_before = rows(database)
    if legacy_owners:
        with psycopg.connect(database("admin")) as conn:
            for name in TABLES:
                keyword = "MATERIALIZED VIEW" if name == "observations_hourly" else "TABLE"
                conn.execute(
                    sql.SQL("ALTER " + keyword + " {} OWNER TO avelren_admin").format(
                        sql.Identifier("public", name),
                    )
                )
            for name in SEQUENCES:
                conn.execute(
                    sql.SQL("ALTER SEQUENCE {} OWNER TO avelren_admin").format(
                        sql.Identifier("public", name),
                    )
                )
    with psycopg.connect(database("admin")) as conn:
        conn.execute("GRANT SELECT ON observations TO PUBLIC")
    before = read_snapshot(database("admin"))
    assert any(row["kind"] == "chunk" for row in before.sections["topology"])
    plan = build_plan(before)
    with psycopg.connect(database("admin")) as conn:
        for statement in plan.forward:
            conn.execute(statement)
    after = read_snapshot(database("admin"))
    assert fingerprint(after) == fingerprint(plan.expected)
    assert rows(database) == data_before
    with psycopg.connect(database("admin")) as conn:
        for statement in plan.inverse:
            conn.execute(statement)
    assert fingerprint(read_snapshot(database("admin"))) == fingerprint(before)
    assert rows(database) == data_before
