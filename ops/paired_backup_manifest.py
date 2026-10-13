"""Строгий completion record для узгодженої PostgreSQL/SQLite-пари.

Sidecar: '<compressed sha256>  <exact basename>\\n'. Manifest не хешує себе.
Читач використовує load_manifest, щоб відхилити duplicate keys до validation.
"""

import gzip
import hashlib
import json
import re
import zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path


class ManifestError(ValueError):
    """Безпечна категорія помилки без шляхів або сирих значень."""


def _require(condition, category="manifest_invalid"):
    if not condition:
        raise ManifestError(category)


def _fields(value, fields):
    _require(type(value) is dict and set(value) == set(fields))


def _integer(value, minimum=0):
    _require(type(value) is int and value >= minimum)


def _hash(value, length=64):
    _require(isinstance(value, str) and re.fullmatch(f"[0-9a-f]{{{length}}}", value))


def _utc(value):
    _require(isinstance(value, str))
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ManifestError("timestamp_invalid") from exc
    _require(parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0), "timestamp_invalid")
    return parsed


def _backup_time(value):
    _require(isinstance(value, str) and re.fullmatch("[0-9]{8}-[0-9]{6}", value))
    try:
        return datetime.strptime(value, "%Y%m%d-%H%M%S").replace(tzinfo=UTC)
    except ValueError as exc:
        raise ManifestError("backup_id_invalid") from exc


def _tier(at):
    return "monthly" if at.day == 1 else "weekly" if at.weekday() == 6 else "daily"


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "duplicate_json_key")
        result[key] = value
    return result


def load_manifest(text: str | bytes) -> dict:
    """Parse JSON with duplicate-key rejection at every nesting level."""
    try:
        value = json.loads(text, object_pairs_hook=_unique_object)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ManifestError("manifest_json_invalid") from exc
    return validate_manifest(value)


def validate_manifest(value: object) -> dict:
    _fields(
        value,
        [
            "format_version",
            "backup_id",
            "tier",
            "artifacts",
            "snapshots",
            "runtime",
            "spool",
            "writer_resumed",
        ],
    )
    _require(type(value["format_version"]) is int and value["format_version"] == 1)
    at = _backup_time(value["backup_id"])
    _require(value["tier"] == _tier(at))
    _require(value["writer_resumed"] is True, "writer_not_resumed")
    _fields(value["artifacts"], ["sql", "spool"])
    for key, suffix in [("sql", ".sql.gz"), ("spool", ".spool.sqlite3.gz")]:
        record = value["artifacts"][key]
        _fields(record, ["name", "sha256", "bytes"])
        _require(record["name"] == f"avelren-{value['backup_id']}{suffix}", "artifact_name_invalid")
        _hash(record["sha256"])
        _integer(record["bytes"], 1)
    _fields(value["snapshots"], ["sql", "spool"])
    times = {}
    for key in ["sql", "spool"]:
        record = value["snapshots"][key]
        _fields(record, ["started_at", "finished_at"])
        times[key] = (_utc(record["started_at"]), _utc(record["finished_at"]))
        _require(times[key][0] <= times[key][1], "snapshot_order_invalid")
    _require(times["sql"][1] <= times["spool"][0], "snapshot_order_invalid")
    runtime = value["runtime"]
    _fields(runtime, ["source_commit", "image_id", "container_id", "restart_count", "started_at"])
    _hash(runtime["source_commit"], 40)
    _require(isinstance(runtime["image_id"], str) and runtime["image_id"].startswith("sha256:"))
    _hash(runtime["image_id"][7:])
    _hash(runtime["container_id"])
    _integer(runtime["restart_count"])
    _require(_utc(runtime["started_at"]) <= times["sql"][0], "runtime_time_invalid")
    spool = value["spool"]
    _fields(
        spool,
        [
            "schema_version",
            "payload_version",
            "state_counts",
            "payload_count",
            "cycle_range",
            "sha256",
            "bytes",
        ],
    )
    for key in ["schema_version", "payload_version"]:
        _require(type(spool[key]) is int and spool[key] == 1, "spool_version_invalid")
    _fields(spool["state_counts"], ["started", "pending", "acked"])
    for count in spool["state_counts"].values():
        _integer(count)
    _integer(spool["payload_count"])
    _require(
        spool["payload_count"] == spool["state_counts"]["pending"] + spool["state_counts"]["acked"]
    )
    _hash(spool["sha256"])
    _integer(spool["bytes"], 1)
    cycle_range = spool["cycle_range"]
    _fields(cycle_range, ["first_seq", "last_seq", "first_at", "last_at"])
    count = sum(spool["state_counts"].values())
    if count == 0:
        _require(all(field is None for field in cycle_range.values()))
    else:
        _integer(cycle_range["first_seq"], 1)
        _integer(cycle_range["last_seq"], 1)
        _require(cycle_range["last_seq"] - cycle_range["first_seq"] + 1 >= count)
        _require(_utc(cycle_range["first_at"]) <= _utc(cycle_range["last_at"]) <= times["spool"][1])
    # Detach from caller-owned objects; only checked JSON values leave the boundary.
    return json.loads(json.dumps(value))


def build_manifest(
    backup_id: str,
    artifacts: dict,
    snapshots: dict,
    runtime: dict,
    spool: dict,
    writer_resumed: bool,
) -> dict:
    return validate_manifest(
        {
            "format_version": 1,
            "backup_id": backup_id,
            "tier": _tier(_backup_time(backup_id)),
            "artifacts": artifacts,
            "snapshots": snapshots,
            "runtime": runtime,
            "spool": spool,
            "writer_resumed": writer_resumed,
        }
    )


def verify_local_pair(manifest: dict, directory: Path) -> dict:
    """Verify compressed bytes and unambiguous sidecars, never mix backup IDs."""
    value = validate_manifest(manifest)
    directory = Path(directory)
    try:
        for kind, artifact in value["artifacts"].items():
            path = directory / artifact["name"]
            sidecar = directory / (artifact["name"] + ".sha256")
            _require(
                path.is_file()
                and not path.is_symlink()
                and sidecar.is_file()
                and not sidecar.is_symlink(),
                "pair_incomplete",
            )
            _require(path.stat().st_size == artifact["bytes"], "artifact_size_invalid")
            with path.open("rb") as stream:
                _require(
                    hashlib.file_digest(stream, "sha256").hexdigest() == artifact["sha256"],
                    "artifact_hash_invalid",
                )
            _require(
                sidecar.read_text(encoding="ascii")
                == f"{artifact['sha256']}  {artifact['name']}\n",
                "sidecar_invalid",
            )
            # Streaming gzip validation checks trailer/CRC without retaining payloads.
            uncompressed_hash = hashlib.sha256()
            uncompressed_bytes = 0
            with gzip.open(path, "rb") as stream:
                while chunk := stream.read(1024 * 1024):
                    if kind == "spool":
                        uncompressed_hash.update(chunk)
                        uncompressed_bytes += len(chunk)
            if kind == "spool":
                _require(
                    uncompressed_hash.hexdigest() == value["spool"]["sha256"]
                    and uncompressed_bytes == value["spool"]["bytes"],
                    "spool_summary_invalid",
                )
    except (OSError, EOFError, UnicodeError, zlib.error) as exc:
        raise ManifestError("pair_validation_failed") from exc
    return value


def retention_candidates(manifests: list[dict], tier: str, keep: int) -> list[str]:
    """Return old complete IDs in one tier; ignore legacy/invalid records."""
    _require(tier in {"daily", "weekly", "monthly"})
    _integer(keep, 1)
    _require(type(manifests) is list)
    valid = set()
    for candidate in manifests:
        try:
            value = validate_manifest(candidate)
        except ManifestError:
            continue
        if value["tier"] == tier:
            valid.add(value["backup_id"])
    return sorted(valid)[:-keep]
