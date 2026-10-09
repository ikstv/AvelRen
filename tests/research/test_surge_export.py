"""Контракт мінімального read-only export, без мережі."""

import gzip
import json
from datetime import UTC, datetime, timedelta

import pytest

from tools.surge_experiment.export import MISSING_IDS, query_for, write_archive

T = datetime(2026, 8, 6, tzinfo=UTC)


def test_export_rejects_unbounded_or_naive_query():
    for start, end in (
        (T, T + timedelta(days=2)),
        (T, T),
        (T.replace(tzinfo=None), T + timedelta(days=1)),
    ):
        with pytest.raises(ValueError):
            query_for("observations", start, end)
    with pytest.raises(ValueError):
        query_for("subscriptions", T, T + timedelta(days=1))
    sql, params = query_for("observations", T, T + timedelta(days=1))
    assert "checkpoint_id=ANY(%s)" in sql
    assert tuple(params[0]) == MISSING_IDS
    assert "time>=%s AND time<%s" in sql


def test_archive_never_accepts_partial_or_duplicate_export(tmp_path):
    row = [2, T.timestamp(), 20, False]
    destination = tmp_path / "history.json.gz"
    with pytest.raises(ValueError, match="count"):
        write_archive(
            destination, "observations", [[row]], {2: 2}, T, T + timedelta(days=1)
        )
    assert not destination.exists()
    with pytest.raises(ValueError, match="duplicate"):
        write_archive(
            tmp_path / "duplicates.gz",
            "observations",
            [[row, row]],
            {2: 2},
            T,
            T + timedelta(days=1),
        )
    with pytest.raises(ValueError, match="row"):
        write_archive(
            tmp_path / "extra.gz",
            "observations",
            [[row + ["secret"]]],
            {2: 1},
            T,
            T + timedelta(days=1),
        )


def test_archive_counts_hashes_and_atomic_completion(tmp_path):
    rows = [[2, T.timestamp(), 20, False], [3, T.timestamp(), 0, True]]
    target = tmp_path / "complete.gz"
    receipt = write_archive(
        target,
        "observations",
        [[rows[0]], [rows[1]]],
        {2: 1, 3: 1},
        T,
        T + timedelta(days=1),
    )
    assert receipt["records"] == 2 and len(receipt["sha256"]) == 64
    assert json.loads(gzip.decompress(target.read_bytes())) == rows
    assert not target.with_name(target.name + ".partial").exists()
    with pytest.raises(FileExistsError):
        write_archive(target, "observations", [], {}, T, T + timedelta(days=1))


def test_cycle_archive_accepts_only_safe_reason_and_exact_types(tmp_path):
    for row in (
        [T.timestamp(), False, 100, "https://secret"],
        [T.timestamp(), 1, 100, None],
        [T.timestamp(), True, 100, "unknown"],
        [T.timestamp(), False, -1, "unknown"],
    ):
        with pytest.raises(ValueError, match="row"):
            write_archive(
                tmp_path / (str(abs(hash(str(row)))) + ".gz"),
                "cycles",
                [[row]],
                {"cycles": 1},
                T,
                T + timedelta(days=1),
            )
    assert (
        write_archive(
            tmp_path / "cycles.gz",
            "cycles",
            [[[T.timestamp(), False, None, "unknown"]]],
            {"cycles": 1},
            T,
            T + timedelta(days=1),
        )["records"]
        == 1
    )
