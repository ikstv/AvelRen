"""Лише локальні gzip/JSON з перевіркою SHA до розпакування."""
import gzip
import hashlib
import json
import math
from datetime import UTC, datetime
from pathlib import Path

from .contracts import Dataset, ObservationRow


def local_path(value: str | Path) -> Path:
    text = str(value)
    if "://" in text or text.startswith(("//", "\\\\")):
        raise ValueError("local path required")
    path = Path(value).resolve()
    if str(path).startswith(("//", "\\\\")):
        raise ValueError("local path required")
    return path


def timestamp(value) -> datetime:
    if isinstance(value, str):
        result = datetime.fromisoformat(value)
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError("aware timestamp required")
        return result.astimezone(UTC)
    if type(value) in (int, float) and math.isfinite(value):
        return datetime.fromtimestamp(value, UTC)
    raise ValueError("invalid timestamp")


def load_dataset(paths: list[Path], expected_hashes: dict[str, str]) -> Dataset:
    files = [local_path(p) for p in paths]
    names = [p.name for p in files]
    if not files or len(names) != len(set(names)) or set(names) != set(expected_hashes):
        raise ValueError("input files and hashes must match exactly")
    rows, seen, hashes = {}, set(), {}
    for path in files:
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        if digest != expected_hashes[path.name]:
            raise ValueError("input hash mismatch")
        hashes[path.name] = digest
        try:
            records = json.loads(gzip.decompress(data))
        except (ValueError, OSError, EOFError):
            raise ValueError("invalid compressed JSON input") from None
        if not isinstance(records, list):
            raise ValueError("input must be an array")  # noqa: TRY004 - invalid external JSON schema
        for index, record in enumerate(records):
            try:
                if not isinstance(record, list) or len(record) != 4:
                    raise ValueError
                queue_id, raw_time, count, paused = record
                if type(queue_id) is not int or queue_id <= 0:
                    raise ValueError
                if type(count) is not int or count < 0 or type(paused) is not bool:
                    raise ValueError
                time = timestamp(raw_time)
            except (ValueError, TypeError, OverflowError, OSError):
                raise ValueError(f"invalid observation row at index {index}") from None
            key = (queue_id, time)
            if key in seen:
                raise ValueError("duplicate observation key")
            seen.add(key)
            rows.setdefault(queue_id, []).append(ObservationRow(queue_id, time, count, paused))
    if not rows:
        raise ValueError("empty observation dataset")
    return Dataset({k: tuple(sorted(v, key=lambda r: r.time)) for k, v in sorted(rows.items())}, hashes)
