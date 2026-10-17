"""Local durable journal for one collector's normalized cycles.

Only this module writes the SQLite database. The producer and replay worker use
short synchronous transactions so neither can observe a partially captured cycle.
"""

import hashlib
import json
import os
import re
import shutil
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .echerha import FetchResult
from .models import Country, WorkloadItem

SCHEMA_VERSION = 1
MIN_MAINTENANCE_FREE_BYTES = 2_147_483_648


class SpoolUnavailable(RuntimeError):
    """Capture/replay cannot be guaranteed without operator intervention."""


@dataclass(frozen=True)
class CapturedCycle:
    seq: int
    at: datetime
    http_status: int | None
    duration_ms: int
    body_sha256: str | None
    error: str | None
    countries: tuple[Country, ...]
    items: tuple[WorkloadItem, ...]


@dataclass(frozen=True)
class SpoolStatus:
    pending_count: int
    oldest_pending_at: datetime | None
    capture_only: bool
    mode_ack: bool | None
    last_error: str | None
    max_cycle_bytes: int
    acked_count: int
    spool_bytes: int


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("cycle time must be timezone-aware")
    return value.astimezone(UTC)


def _source_error(result: FetchResult) -> str | None:
    """Persist a reason, never an exception's rejected input or transport details."""
    if result.error is None:
        return None
    if result.error.startswith("parse:"):
        return "parse: invalid workload response"
    if result.error in {
        "configuration: ECHERHA_DEVICE_ID must be a valid non-nil UUID",
        "configuration: ECHERHA_DEVICE_NAME must be 1–120 printable ASCII characters",
    }:
        return result.error
    if result.http_status is not None and result.http_status != 200:
        return f"HTTP {result.http_status}"
    kind = result.error.partition(":")[0]
    if re.fullmatch(
        r"(?:ReadTimeout|ConnectTimeout|WriteTimeout|PoolTimeout|ReadError|ConnectError|"
        r"WriteError|CloseError|RemoteProtocolError|LocalProtocolError|ProxyError|"
        r"UnsupportedProtocol|DecodingError|TooManyRedirects|HTTPError): "
        r"reason=(?:dns|tls|connection_refused|network_unreachable|host_unreachable|"
        r"connection_reset|timeout|os_error|unknown) errno=(?:-?[0-9]{1,8}|none)",
        result.error,
    ):
        return result.error
    if kind in {
        "ReadTimeout", "ConnectTimeout", "WriteTimeout", "PoolTimeout",
        "ReadError", "ConnectError", "WriteError", "CloseError",
        "RemoteProtocolError", "LocalProtocolError", "ProxyError",
        "UnsupportedProtocol", "DecodingError", "TooManyRedirects",
    }:
        return kind
    return "source_error"


class SpoolStore:
    def __init__(self, path: Path, max_bytes: int = 1_073_741_824) -> None:
        self.path = Path(path)
        self.max_bytes = max_bytes
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if os.name == "posix":
            os.chmod(self.path.parent, 0o700)
        try:
            self.conn = sqlite3.connect(self.path, timeout=10, isolation_level=None)
            self.conn.execute("PRAGMA auto_vacuum=INCREMENTAL")
            if self.conn.execute("PRAGMA auto_vacuum").fetchone()[0] != 2:
                self.conn.close()
                raise SpoolUnavailable("spool needs offline incremental-vacuum conversion")
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=FULL")
            self.conn.execute("PRAGMA busy_timeout=10000")
            self.conn.execute("PRAGMA foreign_keys=ON")
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS cycles (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    at TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (state IN ('started','pending','acked')),
                    payload_version INTEGER,
                    payload BLOB,
                    payload_sha256 TEXT,
                    acked_at TEXT
                )
            """)
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
            """)
            with self._transaction():
                self.conn.execute(
                    "INSERT OR IGNORE INTO meta(key,value) VALUES ('schema_version',?)",
                    (str(SCHEMA_VERSION),),
                )
                self.conn.execute(
                    "INSERT OR IGNORE INTO meta(key,value) VALUES ('capture_only','0')"
                )
            if self._meta("schema_version") != str(SCHEMA_VERSION):
                raise SpoolUnavailable("unknown spool schema version")
            if self.conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise SpoolUnavailable("spool integrity check failed")
            if os.name == "posix":
                for suffix in ("", "-wal", "-shm"):
                    candidate = Path(f"{self.path}{suffix}")
                    if candidate.exists():
                        os.chmod(candidate, 0o600)
        except sqlite3.Error as exc:
            raise SpoolUnavailable(f"cannot open spool: {exc}") from exc

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def _transaction(self):
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield
            except BaseException:
                self.conn.rollback()
                raise
            else:
                self.conn.commit()
        except sqlite3.Error as exc:
            self.conn.rollback()
            raise SpoolUnavailable(f"spool transaction failed: {exc}") from exc

    def _meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def _size(self) -> int:
        return sum(
            candidate.stat().st_size
            for candidate in (self.path, Path(f"{self.path}-wal"), Path(f"{self.path}-shm"))
            if candidate.exists()
        )

    def _check_quota(self, extra: int = 0) -> None:
        if self._size() + extra > self.max_bytes:
            raise SpoolUnavailable("spool quota exceeded")

    def begin(self, at: datetime) -> int:
        self._check_quota()
        try:
            with self._transaction():
                cursor = self.conn.execute(
                    "INSERT INTO cycles(at,state) VALUES (?, 'started')", (_utc(at).isoformat(),)
                )
            self._check_quota()
            return int(cursor.lastrowid)
        except sqlite3.Error as exc:
            raise SpoolUnavailable(f"cannot start cycle: {exc}") from exc

    def finish(self, seq: int, result: FetchResult, vehicle_type: int) -> None:
        countries = result.response.filters.countries if result.response is not None else []
        items = (
            [item for item in result.response.data if item.for_vehicle_type == vehicle_type]
            if result.response is not None else []
        )
        payload = _canonical({
            "http_status": result.http_status,
            "duration_ms": result.duration_ms,
            "body_sha256": result.body_sha256,
            "error": _source_error(result),
            "countries": [country.model_dump(exclude={"flag_emoji"}) for country in countries],
            "items": [item.model_dump(by_alias=True) for item in items],
        })
        digest = hashlib.sha256(payload).hexdigest()
        self._check_quota(len(payload))
        try:
            with self._transaction():
                cursor = self.conn.execute(
                    """UPDATE cycles SET state='pending', payload_version=?, payload=?,
                       payload_sha256=? WHERE seq=? AND state='started'""",
                    (SCHEMA_VERSION, payload, digest, seq),
                )
                if cursor.rowcount != 1:
                    raise SpoolUnavailable("cycle not in started state")
                if result.error is None and items:
                    max_bytes = int(self._meta("max_cycle_bytes") or "0")
                    self.conn.execute(
                        "INSERT OR REPLACE INTO meta(key,value) VALUES ('max_cycle_bytes',?)",
                        (str(max(max_bytes, len(payload))),),
                    )
        except sqlite3.Error as exc:
            raise SpoolUnavailable(f"cannot finish cycle: {exc}") from exc
        self._check_quota()

    def recover_started(self) -> None:
        interrupted = _canonical({
            "http_status": None, "duration_ms": 0, "body_sha256": None,
            "error": "interrupted_before_durable_result", "countries": [], "items": [],
        })
        try:
            with self._transaction():
                self.conn.execute(
                    """UPDATE cycles SET state='pending', payload_version=?, payload=?,
                       payload_sha256=? WHERE state='started'""",
                    (SCHEMA_VERSION, interrupted, hashlib.sha256(interrupted).hexdigest()),
                )
        except sqlite3.Error as exc:
            raise SpoolUnavailable(f"cannot recover cycles: {exc}") from exc

    def next_pending(self) -> CapturedCycle | None:
        try:
            row = self.conn.execute(
                """SELECT seq,at,payload_version,payload,payload_sha256 FROM cycles
                   WHERE state='pending' ORDER BY seq LIMIT 1"""
            ).fetchone()
        except sqlite3.Error as exc:
            raise SpoolUnavailable(f"cannot read pending cycle: {exc}") from exc
        if row is None:
            return None
        seq, at, version, payload, digest = row
        if version != SCHEMA_VERSION or not isinstance(payload, bytes):
            raise SpoolUnavailable(f"unknown or incomplete payload for cycle {seq}")
        if hashlib.sha256(payload).hexdigest() != digest:
            raise SpoolUnavailable(f"payload checksum mismatch for cycle {seq}")
        try:
            data = json.loads(payload)
            return CapturedCycle(
                seq=seq, at=datetime.fromisoformat(at), http_status=data["http_status"],
                duration_ms=data["duration_ms"], body_sha256=data["body_sha256"],
                error=data["error"],
                countries=tuple(Country.model_validate(value) for value in data["countries"]),
                items=tuple(WorkloadItem.model_validate(value) for value in data["items"]),
            )
        except (ValueError, KeyError, TypeError) as exc:
            raise SpoolUnavailable(f"invalid payload for cycle {seq}") from exc

    def ack(self, seq: int) -> None:
        try:
            with self._transaction():
                cursor = self.conn.execute(
                    "UPDATE cycles SET state='acked',acked_at=? WHERE seq=? AND state='pending'",
                    (datetime.now(UTC).isoformat(), seq),
                )
                if cursor.rowcount != 1:
                    raise SpoolUnavailable("cannot ack a non-pending cycle")
        except sqlite3.Error as exc:
            raise SpoolUnavailable(f"cannot ack cycle: {exc}") from exc

    def prune_acked(self, now: datetime) -> None:
        try:
            with self._transaction():
                self.conn.execute(
                    "DELETE FROM meta WHERE key IN (SELECT 'legacy_verified:' || seq FROM cycles "
                    "WHERE state='acked' AND acked_at < ?)",
                    ((_utc(now) - timedelta(hours=24)).isoformat(),),
                )
                deleted = self.conn.execute(
                    "DELETE FROM cycles WHERE state='acked' AND acked_at < ?",
                    ((_utc(now) - timedelta(hours=24)).isoformat(),),
                ).rowcount
            if deleted:
                self.conn.execute("PRAGMA incremental_vacuum").fetchall()
                self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error as exc:
            raise SpoolUnavailable(f"cannot prune cycles: {exc}") from exc

    def set_capture_only(self, enabled: bool) -> None:
        with self._transaction():
            self.conn.execute(
                "INSERT OR REPLACE INTO meta(key,value) VALUES ('capture_only',?)",
                ("1" if enabled else "0",),
            )
            self.conn.execute("DELETE FROM meta WHERE key='mode_ack'")

    def capture_only(self) -> bool:
        return self._meta("capture_only") == "1"

    def set_mode_ack(self, enabled: bool) -> None:
        with self._transaction():
            if self.capture_only() == enabled:
                self.conn.execute(
                    "INSERT OR REPLACE INTO meta(key,value) VALUES ('mode_ack',?)",
                    ("1" if enabled else "0",),
                )

    def record_replay_error(self, message: str | None) -> None:
        with self._transaction():
            if message is None:
                self.conn.execute("DELETE FROM meta WHERE key='last_error'")
            else:
                kind, separator, _ = message.partition(":")
                safe_reason = (
                    kind if separator and re.fullmatch(r"[A-Z][A-Za-z0-9_]{0,79}", kind)
                    else "replay_error"
                )
                self.conn.execute(
                    "INSERT OR REPLACE INTO meta(key,value) VALUES ('last_error',?)",
                    (safe_reason,),
                )

    def status(self) -> SpoolStatus:
        pending, oldest = self.conn.execute(
            "SELECT count(*), min(at) FROM cycles WHERE state='pending'"
        ).fetchone()
        acked = self.conn.execute("SELECT count(*) FROM cycles WHERE state='acked'").fetchone()[0]
        mode_ack = self._meta("mode_ack")
        return SpoolStatus(
            pending_count=pending,
            oldest_pending_at=datetime.fromisoformat(oldest) if oldest else None,
            capture_only=self.capture_only(),
            mode_ack=None if mode_ack is None else mode_ack == "1",
            last_error=self._meta("last_error"),
            max_cycle_bytes=int(self._meta("max_cycle_bytes") or "0"),
            acked_count=acked,
            spool_bytes=self._size(),
        )

    def maintenance_preflight(self, window_minutes: int) -> SpoolStatus:
        if window_minutes <= 0:
            raise ValueError("maintenance window must be positive")
        if self.conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise SpoolUnavailable("spool integrity check failed")
        for seq, version, payload, digest in self.conn.execute(
            "SELECT seq,payload_version,payload,payload_sha256 FROM cycles WHERE state='pending'"
        ):
            if version != SCHEMA_VERSION or not isinstance(payload, bytes):
                raise SpoolUnavailable(f"unknown or incomplete payload for cycle {seq}")
            if hashlib.sha256(payload).hexdigest() != digest:
                raise SpoolUnavailable(f"payload checksum mismatch for cycle {seq}")
        status = self.status()
        if status.max_cycle_bytes == 0:
            raise SpoolUnavailable("no measured collector cycle for maintenance capacity")
        if shutil.disk_usage(self.path.parent).free < MIN_MAINTENANCE_FREE_BYTES:
            raise SpoolUnavailable("insufficient free disk space for maintenance")
        if status.spool_bytes + 2 * status.max_cycle_bytes * window_minutes >= self.max_bytes:
            raise SpoolUnavailable("insufficient spool quota for maintenance")
        return status

    def backup_to(self, path: Path) -> None:
        destination = sqlite3.connect(path)
        try:
            self.conn.backup(destination)
            if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise SpoolUnavailable("backup integrity check failed")
        except sqlite3.Error as exc:
            raise SpoolUnavailable(f"cannot back up spool: {exc}") from exc
        finally:
            destination.close()
