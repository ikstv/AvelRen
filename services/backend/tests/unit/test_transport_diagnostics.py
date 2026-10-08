"""Безпечна причина переживає durable spool; джерело підмінене."""

import asyncio
import errno
import socket
import ssl
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

from avelren import echerha
from avelren.collector_spool import SpoolStore


@pytest.mark.parametrize(
    "cause,code",
    [
        (socket.gaierror(-2, "SECRET_HOST"), "dns"),
        (ssl.SSLError("SECRET_CERT"), "tls"),
        (ConnectionRefusedError(errno.ECONNREFUSED, "SECRET_IP"), "connection_refused"),
        (OSError(errno.ENETUNREACH, "SECRET_IP"), "network_unreachable"),
        (None, "unknown"),
    ],
)
def test_transport_reason_and_duration_survive_spool(monkeypatch, tmp_path, caplog, cause, code):
    monkeypatch.setattr(
        echerha.settings, "echerha_device_id", "11111111-1111-4111-8111-111111111111"
    )
    timer = iter([10.0, 10.125])
    monkeypatch.setattr(echerha, "time", SimpleNamespace(monotonic=lambda: next(timer)))

    def failed(request):
        exc = httpx.ConnectError("SECRET_TOKEN", request=request)
        exc.__cause__ = cause
        raise exc

    async def fetch():
        async with httpx.AsyncClient(transport=httpx.MockTransport(failed)) as client:
            return await echerha.fetch_workload(client)

    result = asyncio.run(fetch())
    assert f"reason={code}" in result.error
    assert "SECRET" not in result.error
    assert "SECRET" not in caplog.text
    assert result.duration_ms == 125
    store = SpoolStore(tmp_path / "cycles.sqlite3")
    store.finish(store.begin(datetime.now(UTC)), result, 1)
    cycle = store.next_pending()
    assert cycle.error == result.error and cycle.duration_ms == 125
    store.close()
