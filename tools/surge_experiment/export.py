"""Обмежений SELECT та перевірка локального export; жодного auto-run/DSN."""

import gzip
import hashlib
import json
import math
import os
from collections import Counter
from datetime import timedelta

MISSING_IDS = (
    2,
    3,
    5,
    7,
    8,
    9,
    10,
    11,
    12,
    13,
    14,
    15,
    16,
    19,
    20,
    31,
    79,
    80,
    84,
    85,
    86,
    88,
    91,
    92,
    93,
    94,
    95,
    96,
    98,
    99,
    100,
    101,
    105,
    107,
)
REASONS = frozenset(
    {
        "dns",
        "tls",
        "connection_refused",
        "network_unreachable",
        "host_unreachable",
        "connection_reset",
        "timeout",
        "os_error",
        "unknown",
        "http",
        "parse",
        "configuration",
    }
)
READ_OPTIONS = (
    "-c default_transaction_read_only=on -c statement_timeout=15000 "
    "-c lock_timeout=1000 -c max_parallel_workers_per_gather=0 -c work_mem=8MB"
)

# Only a class is selected; rejected inputs and exception messages never leave SQL.
_SAFE_ERROR = (
    "^(ReadTimeout|ConnectTimeout|WriteTimeout|PoolTimeout|ReadError|ConnectError|"
    "WriteError|CloseError|RemoteProtocolError|LocalProtocolError|ProxyError|"
    "UnsupportedProtocol|DecodingError|TooManyRedirects|HTTPError): "
    "reason=(dns|tls|connection_refused|network_unreachable|host_unreachable|"
    "connection_reset|timeout|os_error|unknown) errno=(-?[0-9]{1,8}|none)$"
)
_CYCLE_SQL = """SELECT extract(epoch FROM time)::double precision,
    (error IS NULL AND http_status=200) IS TRUE, duration_ms,
    CASE WHEN error IS NULL AND http_status=200 THEN NULL
         WHEN http_status IS NOT NULL AND http_status<>200 THEN 'http'
         WHEN error ~ %s THEN substring(error FROM 'reason=([a-z_]+)')
         WHEN error ~ '^(ReadTimeout|ConnectTimeout|WriteTimeout|PoolTimeout)(:|$)' THEN 'timeout'
         WHEN error LIKE 'parse:%%' THEN 'parse'
         WHEN error LIKE 'configuration:%%' THEN 'configuration'
         ELSE 'unknown' END
    FROM collector_runs WHERE time>=%s AND time<%s ORDER BY time"""


def query_for(kind, start, end):
    if (
        start.tzinfo is None
        or end.tzinfo is None
        or not timedelta(0) < end - start <= timedelta(days=1)
    ):
        raise ValueError("aware interval of at most one day required")
    if kind == "observations":
        return (
            (
                "SELECT checkpoint_id,extract(epoch FROM time)::double precision,"
                "vehicles_in_queue,is_paused FROM observations "
                "WHERE checkpoint_id=ANY(%s) AND time>=%s AND time<%s "
                "ORDER BY time,checkpoint_id"
            ),
            (list(MISSING_IDS), start, end),
        )
    if kind == "cycles":
        return _CYCLE_SQL, (_SAFE_ERROR, start, end)
    raise ValueError("unexpected export kind")


def fetch_chunk(connection, kind, start, end):
    if connection.execute("SHOW transaction_read_only").fetchone()[0] != "on":
        raise ValueError("read-only connection required")
    sql, params = query_for(kind, start, end)
    return [list(row) for row in connection.execute(sql, params).fetchall()]


def _validate_row(kind, row, start, end):
    if not isinstance(row, list) or len(row) != 4:
        raise ValueError("invalid export row")
    offset = 1 if kind == "observations" else 0
    epoch = row[offset]
    if (
        type(epoch) not in (int, float)
        or not math.isfinite(epoch)
        or not start <= epoch < end
    ):
        raise ValueError("invalid export row time")
    if kind == "observations":
        queue, _, count, pause = row
        if (
            type(queue) is not int
            or queue not in MISSING_IDS
            or type(count) is not int
            or count < 0
            or type(pause) is not bool
        ):
            raise ValueError("invalid export row")
        return (queue, epoch), queue
    _, success, duration, reason = row
    if (
        type(success) is not bool
        or (duration is not None and (type(duration) is not int or duration < 0))
        or (success and reason is not None)
        or (not success and reason not in REASONS)
    ):
        raise ValueError("invalid export row")
    return epoch, "cycles"


def write_archive(destination, kind, chunks, expected_counts, start, end):
    """Finish only a complete validated file; leave failed .partial for diagnosis."""
    if kind not in {"observations", "cycles"}:
        raise ValueError("unexpected export kind")
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ValueError("aware export interval required")
    partial = destination.with_name(destination.name + ".partial")
    if destination.exists() or partial.exists():
        raise FileExistsError("export destination already exists")
    counts, seen = Counter(), set()
    with (
        partial.open("xb") as raw,
        gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as out,
    ):
        out.write(b"[")
        first = True
        for chunk in chunks:
            for row in chunk:
                key, group = _validate_row(
                    kind, row, start.timestamp(), end.timestamp()
                )
                if key in seen:
                    raise ValueError("duplicate export key")
                seen.add(key)
                counts[group] += 1
                out.write(
                    (b"" if first else b",")
                    + json.dumps(row, separators=(",", ":")).encode()
                )
                first = False
        out.write(b"]")
    if dict(counts) != {k: v for k, v in expected_counts.items() if v}:
        raise ValueError("export count mismatch")
    digest = hashlib.sha256(partial.read_bytes()).hexdigest()
    # Refuse concurrent destination creation; link is atomic and never overwrites.
    os.link(partial, destination)
    partial.unlink()
    return {
        "records": sum(counts.values()),
        "sha256": digest,
        "bytes": destination.stat().st_size,
    }
