"""Незмінні контракти входу дослідницького стенда."""
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType


@dataclass(frozen=True)
class ObservationRow:
    queue_id: int
    time: datetime
    count: int
    paused: bool


@dataclass(frozen=True)
class Dataset:
    rows: Mapping[int, tuple[ObservationRow, ...]]
    source_hashes: Mapping[str, str]

    def __post_init__(self):
        object.__setattr__(self, "rows", MappingProxyType({k: tuple(v) for k, v in self.rows.items()}))
        object.__setattr__(self, "source_hashes", MappingProxyType(dict(self.source_hashes)))
