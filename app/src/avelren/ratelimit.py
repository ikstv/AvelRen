"""Обмеження частоти запитів.

Захищає не від зловмисника з ботнетом — від найімовірнішого: зациклений
клієнт, кривий скрипт, чи хтось, хто вирішить наробити мільйон пристроїв.

Лічильник у пам'яті процесу, без Redis. Свідомий вибір: зайвий сервіс заради
захисту, який поки нікому не потрібен, — це більше ризику, ніж користі. Коли
екземплярів API стане більше одного, тоді й з'явиться привід для спільного
сховища.
"""

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

# Створення сутностей дороге й рідкісне; читання дешеве й часте.
LIMITS: dict[str, tuple[int, int]] = {
    "write": (30, 60),    # 30 запитів за 60 секунд
    "read": (300, 60),
}

_hits: dict[str, deque[float]] = defaultdict(deque)
TRUSTED_CLIENT_IP_HEADER = "x-avelren-client-ip"


def _client_key(request: Request) -> str:
    # Caddy передає справжню адресу; без нього всі клієнти виглядали б одним.
    forwarded = request.headers.get(TRUSTED_CLIENT_IP_HEADER, "").strip()
    if forwarded:
        try:
            import ipaddress
            return str(ipaddress.ip_address(forwarded))
        except ValueError:
            pass
    return request.client.host if request.client else "unknown"


def check(request: Request, bucket: str = "read") -> None:
    limit, window = LIMITS[bucket]
    key = f"{bucket}:{_client_key(request)}"
    now = time.monotonic()

    hits = _hits[key]
    while hits and now - hits[0] > window:
        hits.popleft()

    if len(hits) >= limit:
        retry = int(window - (now - hits[0])) + 1
        raise HTTPException(
            status_code=429,
            detail="Забагато запитів, спробуйте пізніше",
            headers={"Retry-After": str(retry)},
        )

    hits.append(now)

    # Прибираємо порожні черги, інакше словник ростиме на кожну нову адресу.
    if len(_hits) > 10_000:
        for k in [k for k, v in _hits.items() if not v]:
            del _hits[k]
