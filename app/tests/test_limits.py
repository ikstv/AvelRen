"""Bounded-resource primitives: body-size limit and concurrency gate.

Both are pure unit tests without a DB: the middleware is checked on a minimal
Starlette app, the gate on asyncio tasks. Behavior, not implementation.
"""

import asyncio

import httpx
import pytest
from fastapi import HTTPException
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from avelren import db
from avelren.config import settings
from avelren.limits import BodySizeLimitMiddleware, ConcurrencyGate

LIMIT = 1024


def test_expensive_gate_reserves_pool_headroom() -> None:
    """The expensive gate must be SMALLER than the pool size, otherwise expensive
    reads would exhaust all connections and starve cheap health/workload (#16)."""
    assert settings.api_max_concurrent_expensive < db.POOL_MAX_SIZE


def _echo_app() -> BodySizeLimitMiddleware:
    async def echo(request):  # noqa: ANN001
        body = await request.body()
        return PlainTextResponse(f"got {len(body)}")

    app = Starlette(routes=[Route("/", echo, methods=["POST"])])
    return BodySizeLimitMiddleware(app, max_bytes=LIMIT)


async def _post(app, *, content=None, headers=None) -> httpx.Response:  # noqa: ANN001
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        return await c.post("/", content=content, headers=headers)


# --- Body size bounds ------------------------------------------------------


def test_body_at_limit_is_accepted() -> None:
    r = asyncio.run(_post(_echo_app(), content=b"x" * LIMIT))
    assert r.status_code == 200
    assert r.text == f"got {LIMIT}"


def test_body_over_limit_rejected_via_content_length() -> None:
    r = asyncio.run(_post(_echo_app(), content=b"x" * (LIMIT + 1)))
    assert r.status_code == 413


def test_oversized_chunked_body_without_content_length_rejected() -> None:
    """No Content-Length (chunked) — bytes are counted on the fly, fail-closed."""

    async def gen():
        for _ in range(4):
            yield b"x" * 512  # 2048 together, over the limit

    r = asyncio.run(_post(_echo_app(), content=gen()))
    assert r.status_code == 413


def test_non_http_scope_is_passed_through() -> None:
    """The middleware must not break non-HTTP (lifespan/websocket) scope."""
    seen = {}

    async def app(scope, receive, send):  # noqa: ANN001
        seen["type"] = scope["type"]

    mw = BodySizeLimitMiddleware(app, max_bytes=LIMIT)
    asyncio.run(mw({"type": "lifespan"}, None, None))
    assert seen["type"] == "lifespan"


# --- Concurrency gate ------------------------------------------------------


def test_gate_allows_up_to_limit() -> None:
    gate = ConcurrencyGate(2)

    async def run() -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def hold() -> None:
            async with gate.guard():
                started.set()
                await release.wait()

        t = asyncio.create_task(hold())
        await started.wait()
        async with gate.guard():  # second concurrent — within the limit of 2
            pass
        release.set()
        await t

    asyncio.run(run())


def test_gate_rejects_over_limit_with_503() -> None:
    gate = ConcurrencyGate(1)

    async def run() -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        async def hold() -> None:
            async with gate.guard():
                started.set()
                await release.wait()

        t = asyncio.create_task(hold())
        await started.wait()
        with pytest.raises(HTTPException) as err:
            async with gate.guard():
                pass
        assert err.value.status_code == 503
        release.set()
        await t

    asyncio.run(run())


def test_gate_releases_capacity_after_use() -> None:
    gate = ConcurrencyGate(1)

    async def run() -> None:
        async with gate.guard():
            pass
        async with gate.guard():  # capacity returned
            pass

    asyncio.run(run())


def test_gate_releases_capacity_even_on_error() -> None:
    gate = ConcurrencyGate(1)

    async def run() -> None:
        with pytest.raises(ValueError):
            async with gate.guard():
                raise ValueError("boom")
        async with gate.guard():  # did not "leak" after the exception
            pass

    asyncio.run(run())
