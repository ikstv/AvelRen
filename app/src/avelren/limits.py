"""Public API resource limits (issue #16).

Two primitives, both fail-closed:

* `BodySizeLimitMiddleware` — rejects oversized request bodies (413), both by
  `Content-Length` and by the actual bytes of a chunked request without it.
  Without this, a single request with a gigabyte body would eat process memory
  before validation.
* `ConcurrencyGate` — limits the number of CONCURRENT expensive operations.
  Exceeding it → an immediate 503, without an unbounded wait queue (fail-fast,
  not backpressure, which only postpones the failure). Cheap health/status
  paths do not pass through the gate.
"""

import contextlib
import logging
from collections.abc import AsyncIterator

from fastapi import HTTPException

log = logging.getLogger("avelren.limits")

# All our bodies are small JSON (registration, subscription, token). 16 KiB —
# with headroom for any legitimate body and orders of magnitude below a
# DoS-worthy payload.
MAX_BODY_BYTES = 16 * 1024


class BodySizeLimitMiddleware:
    """ASGI middleware that limits request body size."""

    def __init__(self, app, max_bytes: int = MAX_BODY_BYTES) -> None:  # noqa: ANN001
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001
        if scope["type"] != "http":
            # lifespan / websocket — not our concern, pass through as is.
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        content_length = headers.get(b"content-length")
        if content_length is not None:
            # The declared body is already too large — reject without reading a byte.
            if not content_length.isdigit() or int(content_length) > self.max_bytes:
                await self._reject(send)
                return

        # Bounded read: we buffer the body up to exactly limit+1. This catches
        # both a lying and a missing Content-Length (chunked), without relying on
        # an exception from receive propagating through the app's own error
        # middleware. Memory is bounded by max_bytes, so the buffering itself does
        # not become a DoS vector.
        buffered: list[dict] = []
        received = 0
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] != "http.request":
                buffered.append(message)
                break
            received += len(message.get("body", b""))
            if received > self.max_bytes:
                await self._reject(send)
                return
            buffered.append(message)
            more_body = message.get("more_body", False)

        replay = iter(buffered)

        async def replaying_receive():
            try:
                return next(replay)
            except StopIteration:
                return await receive()

        await self.app(scope, replaying_receive, send)

    async def _reject(self, send) -> None:  # noqa: ANN001
        body = '{"detail":"Request body too large"}'.encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [(b"content-type", b"application/json; charset=utf-8")],
            }
        )
        await send({"type": "http.response.body", "body": body})


class ConcurrencyGate:
    """Limiter of concurrent expensive operations (fail-fast, no queue).

    Single-threaded asyncio: the check and increment happen without an
    intervening await, so the state is consistent without locks.
    """

    def __init__(self, limit: int) -> None:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        self.limit = limit
        self._in_flight = 0

    @contextlib.asynccontextmanager
    async def guard(self) -> AsyncIterator[None]:
        if self._in_flight >= self.limit:
            raise HTTPException(
                status_code=503,
                detail="Service overloaded, please try again later",
                headers={"Retry-After": "1"},
            )
        self._in_flight += 1
        try:
            yield
        finally:
            self._in_flight -= 1
