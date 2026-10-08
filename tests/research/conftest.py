"""Ізоляція дослідження: лише локальні синтетичні дані й loopback."""
import ipaddress
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services/backend/src"))


@pytest.fixture(autouse=True)
def isolated_network(monkeypatch):
    def guarded(original):
        def connect(sock, address):
            if not isinstance(address, tuple):
                raise RuntimeError("research external socket blocked")  # noqa: TRY004 - socket policy
            try:
                local = ipaddress.ip_address(address[0]).is_loopback
            except ValueError:
                local = address[0] == "localhost"
            if not local:
                raise RuntimeError("research external socket blocked")
            return original(sock, address)
        return connect
    monkeypatch.setattr(socket.socket, "connect", guarded(socket.socket.connect))
    monkeypatch.setattr(socket.socket, "connect_ex", guarded(socket.socket.connect_ex))


@pytest.fixture
def input_archive(tmp_path):
    import gzip
    import hashlib
    import json

    def make(rows, name="synthetic.json.gz"):
        path = tmp_path / name
        path.write_bytes(gzip.compress(json.dumps(rows).encode(), mtime=0))
        return path, {path.name: hashlib.sha256(path.read_bytes()).hexdigest()}
    return make
