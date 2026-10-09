"""Часовий purge за реальною залежністю мітки, без shuffle."""
from datetime import datetime

from .labels import Label


def purged_origins(origins: list[datetime], labels: list[Label], start: datetime, end: datetime) -> list[datetime]:
    return [origin for origin, label in zip(origins, labels, strict=True)
            if start <= origin < end and label.dependency_end < end and label.value is not None]
