"""Обмеження ресурсів public API (issue #16).

Два примітиви, обидва fail-closed:

* `BodySizeLimitMiddleware` — відхиляє завеликі тіла запитів (413), і за
  `Content-Length`, і за фактичними байтами chunked-запиту без нього. Без цього
  один запит із гігабайтним тілом з'їв би пам'ять процесу ще до валідації.
* `ConcurrencyGate` — обмежує кількість ОДНОЧАСНИХ дорогих операцій. Перевищення
  → миттєвий 503, без необмеженої черги очікувань (fail-fast, а не backpressure,
  який лише відкладає падіння). Дешеві health/status-шляхи gate не проходять.
"""

import contextlib
import logging
from collections.abc import AsyncIterator

from fastapi import HTTPException

log = logging.getLogger("avelren.limits")

# Усі наші тіла — малий JSON (реєстрація, підписка, токен). 16 КіБ — із запасом
# на будь-яке легітимне тіло й на порядки менше за DoS-корисне навантаження.
MAX_BODY_BYTES = 16 * 1024


class BodySizeLimitMiddleware:
    """ASGI middleware, що обмежує розмір тіла запиту."""

    def __init__(self, app, max_bytes: int = MAX_BODY_BYTES) -> None:  # noqa: ANN001
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001
        if scope["type"] != "http":
            # lifespan / websocket — не наша справа, пропускаємо як є.
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers") or [])
        content_length = headers.get(b"content-length")
        if content_length is not None:
            # Заявлене тіло вже завелике — відмовляємо, не читаючи ні байта.
            if not content_length.isdigit() or int(content_length) > self.max_bytes:
                await self._reject(send)
                return

        # Bounded read: буферизуємо тіло рівно до ліміту+1. Це ловить і брехливий,
        # і відсутній Content-Length (chunked), не покладаючись на те, що виняток
        # із receive прокинеться крізь error-middleware самого застосунку. Пам'ять
        # обмежена max_bytes, тож саме буферування DoS-вектором не стає.
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
        body = '{"detail":"Тіло запиту завелике"}'.encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [(b"content-type", b"application/json; charset=utf-8")],
            }
        )
        await send({"type": "http.response.body", "body": body})


class ConcurrencyGate:
    """Обмежувач одночасних дорогих операцій (fail-fast, без черги).

    Однопотоковий asyncio: перевірка й інкремент відбуваються без проміжного
    await, тож стан узгоджений без блокувань.
    """

    def __init__(self, limit: int) -> None:
        if limit < 1:
            raise ValueError("limit має бути >= 1")
        self.limit = limit
        self._in_flight = 0

    @contextlib.asynccontextmanager
    async def guard(self) -> AsyncIterator[None]:
        if self._in_flight >= self.limit:
            raise HTTPException(
                status_code=503,
                detail="Сервіс перевантажений, спробуйте пізніше",
                headers={"Retry-After": "1"},
            )
        self._in_flight += 1
        try:
            yield
        finally:
            self._in_flight -= 1
