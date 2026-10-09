"""Actual SQL projection on disposable data; no raw errors leave the query."""

from datetime import UTC, datetime, timedelta

import psycopg
from tools.surge_experiment.export import READ_OPTIONS, fetch_chunk

T = datetime(2026, 8, 6, tzinfo=UTC)


def test_export_sql_bounded_minimal_safe_and_readonly(database, conn):
    conn.execute(
        "INSERT INTO checkpoints(id,title,for_vehicle_type) VALUES(2,'test',1),(17,'test',1)"
    )
    conn.execute(
        "INSERT INTO observations(time,checkpoint_id,vehicles_in_queue,"
        "is_paused,wait_time_seconds) "
        "VALUES(%s,2,30,false,0),(%s,17,40,false,0),(%s,2,50,true,0)",
        (T, T, T + timedelta(days=1)),
    )
    errors = [
        None,
        "ConnectError: reason=dns errno=-2",
        "ConnectError: private-token",
        "ReadTimeout",
        "parse: private-payload",
        "ConnectError: reason=dns errno=secret",
        "configuration: private-input",
        "HTTP 503",
    ]
    for i, error in enumerate(errors):
        conn.execute(
            "INSERT INTO collector_runs(time,http_status,duration_ms,error) VALUES(%s,%s,5,%s)",
            (T + timedelta(minutes=i), 503 if i == 7 else (200 if error is None else None), error),
        )
    with psycopg.connect(database("admin"), options=READ_OPTIONS) as reader:
        observations = fetch_chunk(reader, "observations", T, T + timedelta(days=1))
        cycles = fetch_chunk(reader, "cycles", T, T + timedelta(days=1))
        assert observations == [[2, T.timestamp(), 30, False]]
        assert [row[3] for row in cycles] == [
            None,
            "dns",
            "unknown",
            "timeout",
            "parse",
            "unknown",
            "configuration",
            "http",
        ]
        assert [row[1] for row in cycles] == [True] + [False] * 7
        assert "private" not in str(cycles) and "secret" not in str(cycles)
        try:
            reader.execute("INSERT INTO checkpoints(id,title) VALUES(1000,'forbidden')")
        except psycopg.errors.ReadOnlySqlTransaction:
            reader.rollback()
        else:
            raise AssertionError("read-only transaction accepted a write")
