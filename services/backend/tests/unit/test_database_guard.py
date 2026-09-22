"""Відмова небезпечного запуску до будь-яких SQL-запитів."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "marker,dsn",
    [
        ("", ""),
        ("1", "postgresql://avelren_migrator:ci-only@unexpected.invalid/avelren_database_test"),
        ("1", "postgresql://avelren_migrator:ci-only@test-db:5432/avelren"),
    ],
)
@pytest.mark.parametrize("suite", ["database", "database/api"])
def test_database_collection_refuses_unapproved_target(marker, dsn, suite):
    root = Path(__file__).resolve().parents[4]
    env = dict(os.environ, AVELREN_DATABASE_TEST=marker, DATABASE_URL=dsn)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            str(root / "services/backend/pytest.ini"),
            str(root / "services/backend/tests" / suite),
            "--collect-only",
            "-q",
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 4
    assert "require the isolated test_database.sh runner" in result.stderr
