"""Сценарій записує лише всередині одноразового контейнера CI."""

import os
from pathlib import Path

import pytest


def pytest_configure(config):
    if os.environ.get("AVELREN_SNAPSHOT_TEST") != "1" or not Path("/.dockerenv").is_file():
        raise pytest.UsageError("Snapshot tests require the isolated watchdog runner")
