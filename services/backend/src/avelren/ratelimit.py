"""Request rate limiting.

Protects not against an attacker with a botnet — against the most likely case:
a looping client, a broken script, or someone who decides to spin up a million
devices.

The counter lives in process memory, without Redis. A deliberate choice: an
extra service for protection nobody needs yet is more risk than benefit. When
there is more than one API instance, that will be the reason for a shared store.
"""

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

# Creating entities is expensive and rare; reads are cheap and frequent.
LIMITS: dict[str, tuple[int, int]] = {
    "write": (30, 60),    # 30 requests per 60 seconds
    "read": (300, 60),
}

_hits: dict[str, deque[float]] = defaultdict(deque)
TRUSTED_CLIENT_IP_HEADER = "x-avelren-client-ip"


def _client_key(request: Request) -> str:
    # Caddy passes the real address; without it every client would look like one.
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
            detail="Too many requests, please try again later",
            headers={"Retry-After": str(retry)},
        )

    hits.append(now)

    # Remove dead queues, otherwise the dict would grow for every new address.
    # Previously only EMPTY queues were deleted, but a queue empties only when the
    # same key comes back after the window. A client that made one request and
    # vanished left its entry forever — after 10k unique addresses (internet
    # scanners, IPv6 rotation) the cleanup found nothing to remove, and the dict
    # grew unbounded (audit M-4). Now we additionally evict queues whose newest
    # entry is older than its bucket's window: all of its entries would be
    # discarded on the next access anyway, so there is no point keeping them.
    if len(_hits) > 10_000:
        stale = [
            k
            for k, v in _hits.items()
            if not v or now - v[-1] > LIMITS.get(k.split(":", 1)[0], (0, window))[1]
        ]
        for k in stale:
            del _hits[k]
