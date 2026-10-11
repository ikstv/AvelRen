import asyncio
import errno
import hashlib
import logging
import re
import socket
import ssl
import time
from collections.abc import Awaitable, Callable
from uuid import UUID

import httpx

from .config import settings
from .models import WorkloadResponse

log = logging.getLogger(__name__)


class RequestPacer:
    """Монотонний інтервал між спробами одного послідовного collector.

    Викликається після локальних записів і підготовки request, прямо перед send.
    Невдала спроба також займає інтервал; раннє пробудження перевіряємо повторно.
    """

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self.clock = clock
        self.sleep = sleep or asyncio.sleep
        self.last_start: float | None = None

    async def wait(self) -> None:
        if self.last_start is not None:
            while (remaining := self.last_start + 60 - self.clock()) > 0:
                await self.sleep(remaining)
        self.last_start = self.clock()


def response_diagnostic(headers: httpx.Headers) -> str:
    """Лише обмежені hex/UUID ідентифікатори та Retry-After у секундах.

    Невідомі формати, дублікати й надмірні значення відкидаємо цілком:
    не обрізаємо їх і не записуємо довільний текст джерела.
    """
    fields = []
    for header, label in (
        ("x-request-id", "request_id"),
        ("x-correlation-id", "correlation_id"),
    ):
        value = headers.get(header, "")
        if len(value) <= 36 and re.fullmatch(
            r"(?:[0-9a-fA-F]{32}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})",
            value,
        ):
            fields.append(f"{label}={value}")
    retry_after = headers.get("retry-after", "")
    if len(retry_after) <= 6 and re.fullmatch(r"[0-9]{1,6}", retry_after):
        fields.append(f"retry_after_seconds={int(retry_after)}")
    return "".join(f" {field}" for field in fields)


def transport_diagnostic(exc: httpx.HTTPError) -> str:
    """Bounded typed diagnostics, without URLs or exception text."""
    reason = "timeout" if isinstance(exc, httpx.TimeoutException) else "unknown"
    number = None
    current = exc
    seen = set()
    for _ in range(12):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        if isinstance(current, socket.gaierror):
            reason = "dns"
            number = current.errno
            break
        if isinstance(current, ssl.SSLError):
            reason = "tls"
            number = current.errno
            break
        if isinstance(current, OSError) and isinstance(current.errno, int):
            number = current.errno
            reason = {
                errno.ECONNREFUSED: "connection_refused",
                errno.ENETUNREACH: "network_unreachable",
                errno.EHOSTUNREACH: "host_unreachable",
                errno.ECONNRESET: "connection_reset",
                errno.ETIMEDOUT: "timeout",
            }.get(number, "os_error")
        current = current.__cause__ or current.__context__
    name = next(
        (
            kind
            for kind in (
                "ReadTimeout",
                "ConnectTimeout",
                "WriteTimeout",
                "PoolTimeout",
                "ReadError",
                "ConnectError",
                "WriteError",
                "CloseError",
                "RemoteProtocolError",
                "LocalProtocolError",
                "ProxyError",
                "UnsupportedProtocol",
                "DecodingError",
                "TooManyRedirects",
            )
            if isinstance(exc, getattr(httpx, kind))
        ),
        "HTTPError",
    )
    safe_number = str(number) if isinstance(number, int) and abs(number) < 100000000 else "none"
    return f"{name}: reason={reason} errno={safe_number}"


def describe_exception(exc: BaseException) -> str:
    """A never-empty description of an exception (#91).

    Timeouts and some transport errors stringify to '' — recording that leaves
    collector_runs.error blank, and an incident post-mortem a month later reads
    the DB, not the logs (which may be gone). repr() would only wrap the same
    emptiness (ReadTimeout('')), so we lead with the class name: 'ReadTimeout'
    already answers "what happened". When a message exists we keep it.
    """
    return f"{type(exc).__name__}: {exc}".rstrip(": ")


# Guest contract of the official web client (v5). X-User-Agent and device headers
# are added dynamically in fetch_workload from the config.
REQUIRED_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "X-Client-Locale": "uk",
}

# Option A: 1–120 printable ASCII characters. Non-ASCII as HTTP-header bytes is
# unreliable across implementations, so fail-closed rather than "encode it somehow".
_DEVICE_NAME_MAX = 120


def _canonical_device_id(raw: str) -> str:
    """Canonical (lowercase) UUID string or ValueError.

    Policy: a parseable UUID is mandatory; nil is rejected (grammatically valid,
    but names no device); no version/variant restriction — the operator supplies
    any real persistent UUID. We canonicalize via str(UUID(...)), so {braces},
    UPPERCASE, and urn: all reduce to a single form.
    """
    try:
        parsed = UUID(raw)
    except (ValueError, TypeError, AttributeError):
        raise ValueError("configuration: ECHERHA_DEVICE_ID must be a valid non-nil UUID") from None
    if parsed.int == 0:
        raise ValueError("configuration: ECHERHA_DEVICE_ID must be a valid non-nil UUID")
    return str(parsed)


def _validated_device_name(name: str) -> str:
    """1–120 printable ASCII (0x20–0x7E) or ValueError. Fail-closed on empty,
    Unicode, control characters (incl. \\n, \\t), DEL, and longer than 120."""
    if (
        not 1 <= len(name) <= _DEVICE_NAME_MAX
        or not name.isascii()
        or not all(0x20 <= ord(c) <= 0x7E for c in name)
    ):
        raise ValueError(
            "configuration: ECHERHA_DEVICE_NAME must be 1–120 printable ASCII characters"
        )
    return name


class FetchResult:
    def __init__(
        self,
        response: WorkloadResponse | None,
        http_status: int | None,
        duration_ms: int,
        body_sha256: str | None,
        error: str | None,
    ) -> None:
        self.response = response
        self.http_status = http_status
        self.duration_ms = duration_ms
        self.body_sha256 = body_sha256
        self.error = error


async def fetch_workload(
    client: httpx.AsyncClient, *, pacer: RequestPacer | None = None,
) -> FetchResult:
    """A single request to eCherha.

    Source errors are not our outage: we return them as a result, so the cycle
    records the reason and calmly waits for the next minute.
    """
    # Fail-closed: an invalid device config makes no request at all — the reason
    # goes into collector_runs.error, which the watchdog sees. Nothing flies out.
    try:
        device_id = _canonical_device_id(settings.echerha_device_id)
        device_name = _validated_device_name(settings.echerha_device_name)
    except ValueError as exc:
        log.error("%s", exc)
        return FetchResult(None, None, 0, None, str(exc))

    headers = {
        **REQUIRED_HEADERS,
        "X-User-Agent": f"UABorder/{settings.echerha_client_version} Web/1.1.0 User/guest",
        "X-Device-Id": device_id,
        "X-Device-Name": device_name,
        "User-Agent": settings.user_agent,
    }

    # We measure duration with our own monotonic timer: httpx `.elapsed` is
    # available only on the real networking path (under the test transport it is
    # absent), and duration_ms is our telemetry, not part of the wire contract.
    started = time.monotonic()
    try:
        request = client.build_request("GET", settings.workload_url, headers=headers)
        # httpx applies the cookie jar and the client's default headers on
        # build_request, so we strip Authorization/Cookie AFTER building — this
        # covers both inherited headers and a replay of Set-Cookie from the
        # previous cycle. auth=None keeps client auth from re-adding them. No
        # ambient session state.
        request.headers.pop("Authorization", None)
        request.headers.pop("Cookie", None)
        if pacer is not None:
            await pacer.wait()
            # Очікування ліміту не є тривалістю HTTP-запиту.
            started = time.monotonic()
        r = await client.send(request, auth=None, follow_redirects=False)
    except httpx.HTTPError as exc:
        detail = transport_diagnostic(exc)
        duration_ms = int((time.monotonic() - started) * 1000)
        log.warning("request to eCherha failed: %s duration_ms=%s", detail, duration_ms)
        return FetchResult(None, None, duration_ms, None, detail)
    duration_ms = int((time.monotonic() - started) * 1000)

    if r.status_code != 200:
        log.warning("eCherha responded %s%s", r.status_code, response_diagnostic(r.headers))
        return FetchResult(None, r.status_code, duration_ms, None, f"HTTP {r.status_code}")

    body_sha256 = hashlib.sha256(r.content).hexdigest()
    try:
        parsed = WorkloadResponse.model_validate(r.json())
    except ValueError as exc:
        log.error("failed to parse response: %s", exc)
        return FetchResult(None, r.status_code, duration_ms, body_sha256, f"parse: {exc}")

    return FetchResult(parsed, r.status_code, duration_ms, body_sha256, None)
