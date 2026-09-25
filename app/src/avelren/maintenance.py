"""Public, short-lived planned-maintenance state.

The API only reads this file.  A host-side orchestration command publishes it
before it stops the API, so an already-open app can cache the explanation for
the short period during which the server is unavailable.
"""

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

MAINTENANCE_PATH = Path(os.environ.get("AVELREN_MAINTENANCE_FILE", "/telemetry/maintenance.json"))


def read_window(now: datetime) -> dict[str, str] | None:
    """Return one bounded UTC window, or no maintenance for any bad input."""
    try:
        with MAINTENANCE_PATH.open(encoding="utf-8") as source:
            payload = json.loads(source.read(4097))
        if not isinstance(payload, dict):
            return None
        start = datetime.fromisoformat(payload["starts_at"])
        end = datetime.fromisoformat(payload["ends_at"])
        if start.tzinfo is None or end.tzinfo is None:
            return None
        if not 0 < (end - start).total_seconds() <= 900:
            return None
        if end <= now or start > now + timedelta(days=1):
            return None
        return {
            "starts_at": start.astimezone(UTC).isoformat(),
            "ends_at": end.astimezone(UTC).isoformat(),
        }
    except (OSError, ValueError, TypeError, KeyError):
        return None
