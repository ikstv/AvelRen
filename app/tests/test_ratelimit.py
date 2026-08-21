from collections.abc import Mapping

import pytest
from fastapi import HTTPException, Request

from avelren import ratelimit


def make_request(peer: str, headers: Mapping[str, str] | None = None) -> Request:
    scope = {
        "type": "http", "method": "GET", "path": "/",
        "headers": [
            (key.lower().encode(), value.encode())
            for key, value in (headers or {}).items()
        ],
        "client": (peer, 1234), "query_string": b"", "scheme": "http", "server": ("test", 80),
    }
    return Request(scope)


@pytest.fixture(autouse=True)
def clear_hits():
    ratelimit._hits.clear()
    yield
    ratelimit._hits.clear()


def test_spoofed_xff_cannot_choose_rate_limit_key():
    request = make_request("10.0.0.8", {"X-Forwarded-For": "198.51.100.1"})
    assert ratelimit._client_key(request) == "10.0.0.8"


def test_changing_spoofed_xff_cannot_bypass_limit():
    for index in range(30):
        request = make_request(
            "10.0.0.8", {"X-Forwarded-For": f"198.51.100.{index + 1}"}
        )
        ratelimit.check(request, "write")
    with pytest.raises(HTTPException) as error:
        ratelimit.check(make_request("10.0.0.8", {"X-Forwarded-For": "203.0.113.9"}), "write")
    assert error.value.status_code == 429


def test_legitimate_proxied_identity_is_used():
    request = make_request(
        "172.20.0.2", {"X-AvelRen-Client-IP": "203.0.113.10"}
    )
    assert ratelimit._client_key(request) == "203.0.113.10"


def test_distinct_real_clients_remain_distinct():
    first = ratelimit._client_key(make_request("203.0.113.10"))
    second = ratelimit._client_key(make_request("203.0.113.11"))
    assert first != second


@pytest.mark.parametrize("value", ["", "198.51.100.1, 203.0.113.2", "not-an-ip"])
def test_malformed_forwarded_input_falls_back_to_peer(value: str):
    request = make_request(
        "10.0.0.8",
        {"X-AvelRen-Client-IP": value, "X-Forwarded-For": "198.51.100.1"},
    )
    assert ratelimit._client_key(request) == "10.0.0.8"


def test_stale_queues_are_pruned_to_bound_memory():
    """M-4: queues from clients that vanished must not grow unbounded.

    Previously the cleanup deleted only empty queues, so 10k+ one-off requests
    from different addresses stayed in memory forever.
    """
    import time

    now = time.monotonic()
    # 10_001 stale queues (an entry older than the 'read' window = 60s) from
    # clients that no longer come back.
    for index in range(10_001):
        ratelimit._hits[f"read:stale-{index}"].append(now - 3600)

    # A fresh request crosses the cleanup threshold and triggers pruning.
    ratelimit.check(make_request("203.0.113.50"), "read")

    assert len(ratelimit._hits) < 100  # stale ones cleaned out
    assert "read:203.0.113.50" in ratelimit._hits  # the fresh one remained
