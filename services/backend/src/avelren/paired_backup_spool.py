"""Offline SQLite snapshot helper; never starts capture or replay."""

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

from psycopg import AsyncConnection

from .collector_replay import verify_committed_cycle
from .collector_spool import SCHEMA_VERSION, CapturedCycle, SpoolStore, SpoolUnavailable
from .models import Country, WorkloadItem


class SpoolBackupError(ValueError):
    """Categorical failure safe to print without database inputs or paths."""


def decode_cycle(row) -> CapturedCycle:
    """Decode a retained result with the same strict backup payload boundary."""
    seq, at, version, payload, digest = row
    _payload(version, payload, digest)
    data = json.loads(payload, object_pairs_hook=_unique_object)
    return CapturedCycle(
        seq=seq, at=_utc(at), http_status=data["http_status"],
        duration_ms=data["duration_ms"], body_sha256=data["body_sha256"], error=data["error"],
        countries=tuple(Country.model_validate(country) for country in data["countries"]),
        items=tuple(WorkloadItem.model_validate(item) for item in data["items"]),
    )


async def verify_acked_primary(store: SpoolStore, conn: AsyncConnection) -> dict:
    """Read every ACKed result and compare exact primary values without SQLite writes."""
    cycles = observations = 0
    for row in store.conn.execute(
        "SELECT seq,at,payload_version,payload,payload_sha256 FROM cycles "
        "WHERE state='acked' ORDER BY seq"
    ):
        cycle = decode_cycle(row)
        await verify_committed_cycle(conn, cycle)
        cycles += 1
        observations += len(cycle.items)
    return {"acked_cycles": cycles, "acked_observations": observations}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SpoolBackupError("payload_invalid")
        result[key] = value
    return result


def _utc(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise SpoolBackupError("cycle_time_invalid")
    return parsed


def _payload(version, payload, digest):
    if type(version) is not int or version != SCHEMA_VERSION or not isinstance(payload, bytes):
        raise SpoolBackupError("payload_version_or_incomplete")
    if hashlib.sha256(payload).hexdigest() != digest:
        raise SpoolBackupError("payload_digest_invalid")
    data = json.loads(payload, object_pairs_hook=_unique_object)
    if not isinstance(data, dict) or set(data) != {
        "http_status",
        "duration_ms",
        "body_sha256",
        "error",
        "countries",
        "items",
    }:
        raise SpoolBackupError("payload_invalid")
    status, duration, body, error = (
        data[key]
        for key in (
            "http_status",
            "duration_ms",
            "body_sha256",
            "error",
        )
    )
    if status is not None and (type(status) is not int or not 100 <= status <= 599):
        raise SpoolBackupError("payload_invalid")
    if type(duration) is not int or duration < 0:
        raise SpoolBackupError("payload_invalid")
    if body is not None and (not isinstance(body, str) or not re.fullmatch("[0-9a-f]{64}", body)):
        raise SpoolBackupError("payload_invalid")
    if error is not None and not isinstance(error, str):
        raise SpoolBackupError("payload_invalid")
    if not isinstance(data["countries"], list) or not isinstance(data["items"], list):
        raise SpoolBackupError("payload_invalid")
    for country in data["countries"]:
        Country.model_validate(country)
    for item in data["items"]:
        WorkloadItem.model_validate(item)


def _sql_tokens(sql):
    # Normalize layout/keyword case, preserving case and spaces in SQL literals.
    return tuple(
        token if token.startswith("'") else token.lower()
        for token in re.findall(r"'(?:''|[^'])*'|\S", sql)
    )


def _validate_schema(connection):
    expected = {
        "cycles": """CREATE TABLE cycles (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            at TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('started','pending','acked')),
            payload_version INTEGER, payload BLOB, payload_sha256 TEXT, acked_at TEXT
        )""",
        "meta": "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    }
    tables = dict(
        connection.execute(
            "SELECT name,sql FROM sqlite_master WHERE name NOT GLOB 'sqlite_*' AND type='table'"
        )
    )
    if (
        set(tables) != set(expected)
        or connection.execute(
            "SELECT count(*) FROM sqlite_master WHERE name NOT GLOB 'sqlite_*' AND type!='table'"
        ).fetchone()[0]
    ):
        raise SpoolBackupError("spool_schema_invalid")
    for name, sql in expected.items():
        # Version 1 is the exact native DDL, including types, PK, nullability,
        # AUTOINCREMENT and the state CHECK; column names alone are insufficient.
        if _sql_tokens(tables[name]) != _sql_tokens(sql):
            raise SpoolBackupError("spool_schema_invalid")
    sequences = connection.execute("SELECT name,seq FROM sqlite_sequence").fetchall()
    if len(sequences) > 1 or any(
        name != "cycles" or type(seq) is not int or seq < 0 for name, seq in sequences
    ):
        raise SpoolBackupError("spool_sequence_invalid")
    maximum = connection.execute("SELECT max(seq) FROM cycles").fetchone()[0]
    if maximum is not None and (not sequences or sequences[0][1] < maximum):
        raise SpoolBackupError("spool_sequence_invalid")


def inspect_spool(path: Path) -> dict:
    """Validate a static copy without constructor writes, WAL replay or recovery."""
    path = Path(path)
    connection = None
    try:
        if not path.is_file() or path.is_symlink():
            raise SpoolBackupError("spool_missing_or_unsafe")
        wal = Path(f"{path}-wal")
        if wal.exists() and wal.stat().st_size:
            raise SpoolBackupError("spool_not_static")
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise SpoolBackupError("spool_integrity_invalid")
        if connection.execute("SELECT value FROM meta WHERE key='schema_version'").fetchall() != [
            (str(SCHEMA_VERSION),),
        ]:
            raise SpoolBackupError("spool_schema_invalid")
        if connection.execute("PRAGMA auto_vacuum").fetchone()[0] != 2:
            raise SpoolBackupError("spool_schema_invalid")
        _validate_schema(connection)
        counts = {"started": 0, "pending": 0, "acked": 0}
        payload_count = 0
        first = last = None
        previous_at = None
        for seq, at, state, version, payload, digest, acked_at in connection.execute(
            "SELECT seq,at,state,payload_version,payload,payload_sha256,acked_at "
            "FROM cycles ORDER BY seq"
        ):
            cycle_at = _utc(at)
            if type(seq) is not int or seq <= 0 or state not in counts:
                raise SpoolBackupError("cycle_invalid")
            if last is not None and seq <= last[0]:
                raise SpoolBackupError("cycle_sequence_invalid")
            if previous_at is not None and cycle_at < previous_at:
                raise SpoolBackupError("cycle_range_invalid")
            previous_at = cycle_at
            if first is None:
                first = (seq, at)
            last = (seq, at)
            counts[state] += 1
            if state == "started":
                if any(value is not None for value in (version, payload, digest, acked_at)):
                    raise SpoolBackupError("started_cycle_invalid")
            else:
                _payload(version, payload, digest)
                payload_count += 1
                if state == "acked":
                    if _utc(acked_at) < cycle_at:
                        raise SpoolBackupError("cycle_time_invalid")
                elif acked_at is not None:
                    raise SpoolBackupError("pending_cycle_invalid")
        cycle_range = {
            "first_seq": first[0] if first else None,
            "last_seq": last[0] if last else None,
            "first_at": first[1] if first else None,
            "last_at": last[1] if last else None,
        }
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        return {
            "schema_version": SCHEMA_VERSION,
            "payload_version": SCHEMA_VERSION,
            "state_counts": counts,
            "payload_count": payload_count,
            "cycle_range": cycle_range,
            "sha256": digest,
            "bytes": path.stat().st_size,
        }
    except SpoolBackupError:
        raise
    except (OSError, sqlite3.Error, ValueError, TypeError, KeyError, OverflowError) as from_error:
        raise SpoolBackupError("spool_validation_failed") from from_error
    finally:
        if connection is not None:
            connection.close()


def snapshot_spool(source: Path, destination: Path) -> dict:
    """Use native Online Backup and inspect its private, detached result."""
    source, destination = Path(source), Path(destination)
    store = None
    created = False
    try:
        if destination.resolve().is_relative_to(source.resolve().parent):
            raise SpoolBackupError("snapshot_destination_unsafe")
        if not source.is_file() or source.is_symlink():
            raise SpoolBackupError("spool_missing_or_unsafe")
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name == "posix":
            os.chmod(destination.parent, 0o700)
        # Exclusive creation prevents accidental overwrite of another backup.
        with destination.open("xb"):
            created = True
        if os.name == "posix":
            os.chmod(destination, 0o600)
        store = SpoolStore(source)
        store.backup_to(destination)
        return inspect_spool(destination)
    except (SpoolBackupError, OSError, sqlite3.Error, SpoolUnavailable) as exc:
        if created:
            try:
                destination.unlink(missing_ok=True)
            except OSError as cleanup_error:
                raise SpoolBackupError("snapshot_cleanup_failed") from cleanup_error
        if isinstance(exc, SpoolBackupError):
            raise
        raise SpoolBackupError("snapshot_failed") from exc
    finally:
        if store is not None:
            store.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("snapshot", "inspect"):
        arguments = commands.add_parser(command)
        arguments.add_argument("--source", type=Path, required=True)
        if command == "snapshot":
            arguments.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        summary = (
            snapshot_spool(args.source, args.output)
            if args.command == "snapshot"
            else inspect_spool(args.source)
        )
    except SpoolBackupError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
