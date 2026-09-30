"""Новий статус не змінює стиснену історію та зберігає старий INSERT."""

import psycopg
import pytest

from conftest import MIGRATIONS


@pytest.mark.parametrize("database", [14], indirect=True)
def test_status_migration_preserves_compressed_legacy(database):
    from avelren import migrate

    with psycopg.connect(database("admin"), autocommit=True) as conn:
        conn.execute("INSERT INTO checkpoints(id,title,for_vehicle_type) VALUES (123,'fixture',1)")
        conn.execute(
            "INSERT INTO observations VALUES "
            "(now()-interval '14 days',123,0,80,false),"
            "(now()-interval '14 days 1 minute',123,3600,81,false),"
            "(now()-interval '14 days 2 minutes',123,-1,82,false)"
        )
        before = conn.execute("SELECT * FROM observations ORDER BY time").fetchall()
        conn.execute("SELECT compress_chunk(c) FROM show_chunks('observations') c")
        compressed_before = conn.execute(
            "SELECT count(*) FROM timescaledb_information.chunks "
            "WHERE hypertable_name='observations' AND is_compressed"
        ).fetchone()[0]
        assert compressed_before > 0

    assert migrate.run(MIGRATIONS) == 0
    with psycopg.connect(database("admin")) as conn:
        columns = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='observations'"
        ).fetchall()
        assert ("wait_time_status",) in columns
        assert (
            conn.execute(
                "SELECT time,checkpoint_id,wait_time_seconds,vehicles_in_queue,is_paused "
                "FROM observations ORDER BY time"
            ).fetchall()
            == before
        )
        assert conn.execute("SELECT DISTINCT wait_time_status FROM observations").fetchall() == [
            ("legacy_unknown",)
        ]
        assert (
            conn.execute(
                "SELECT count(*) FROM timescaledb_information.chunks "
                "WHERE hypertable_name='observations' AND is_compressed"
            ).fetchone()[0]
            == compressed_before
        )


def test_status_checks_and_old_insert(database):
    with psycopg.connect(database("admin"), autocommit=True) as conn:
        columns = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name='observations'"
        ).fetchall()
        assert ("wait_time_status",) in columns
        conn.execute("INSERT INTO checkpoints(id,title,for_vehicle_type) VALUES (123,'fixture',1)")
        old = conn.execute(
            "INSERT INTO observations(time,checkpoint_id,wait_time_seconds,vehicles_in_queue,is_paused) "
            "VALUES(now(),123,0,80,false) RETURNING wait_time_status"
        ).fetchone()
        assert old == ("legacy_unknown",)
        for seconds, status in [(0, "reported"), (0, "missing"), (-1, "legacy_unknown")]:
            assert conn.execute(
                "INSERT INTO observations VALUES(now(),123,%s,80,false,%s) "
                "RETURNING wait_time_status",
                (seconds, status),
            ).fetchone() == (status,)
        for seconds, status in [(1, "missing"), (-1, "reported"), (0, "unexpected")]:
            with pytest.raises(psycopg.errors.CheckViolation):
                conn.execute(
                    "INSERT INTO observations VALUES(now(),123,%s,80,false,%s)", (seconds, status)
                )
