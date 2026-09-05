from collections.abc import Mapping
from pathlib import Path

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


# --- Coverage contract ------------------------------------------------------


def _route_handlers():
    """Every HTTP handler of both routers, paired with its AST body."""
    import ast

    from avelren import api, subscriptions_api

    for module in (api, subscriptions_api):
        tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            routes = [
                decorator
                for decorator in node.decorator_list
                if isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr in {"get", "post", "put", "delete"}
            ]
            if not routes:
                continue
            yield f"{routes[0].func.attr.upper()} {routes[0].args[0].value}", node


def test_every_route_is_rate_limited():
    """No path may be left without a limit.

    Six routes were unlimited before this contract: /health, /thresholds,
    GET /subscriptions, /active-alerts, GET /eta-targets and /admin/telemetry.
    Each of them spends a pool connection (max_size=5) BEFORE credentials are
    checked, so an unauthenticated client could exhaust the pool with garbage
    headers alone.

    The check is static rather than request-driven on purpose: otherwise it
    would need a database and would stay silent exactly where it is needed —
    on a newly added endpoint whose author forgot the limit.
    """
    import ast

    unlimited = [
        name
        for name, node in _route_handlers()
        if not any(
            isinstance(call.func, ast.Name) and call.func.id == "rate_check"
            for call in ast.walk(node)
            if isinstance(call, ast.Call)
        )
    ]
    assert not unlimited, "endpoints without rate_check: " + ", ".join(unlimited)


def test_route_coverage_check_sees_all_routes():
    """Guard for the guard above.

    If `_route_handlers` ever stopped finding handlers — a change in decorator
    style, a move to another module — `test_every_route_is_rate_limited` would
    pass over an empty list and become decoration.
    """
    from avelren.api import app

    # The OpenAPI schema, not `app.routes`: FastAPI 0.115 flattened
    # include_router straight into `app.routes`, while newer versions wrap the
    # included router in a private object, and a flat walk would silently lose
    # every subscription endpoint. The schema is a public contract on both, and
    # carries no /docs, /redoc or /openapi.json of its own.
    schema = app.openapi()
    declared = {
        f"{method.upper()} {path}"
        for path, operations in schema["paths"].items()
        for method in operations
        if method.upper() not in {"HEAD", "OPTIONS"}
    }
    discovered = {name for name, _ in _route_handlers()}
    assert declared == discovered, (
        f"registered paths and AST-discovered paths diverge: "
        f"only in app {declared - discovered}, only in AST {discovered - declared}"
    )
