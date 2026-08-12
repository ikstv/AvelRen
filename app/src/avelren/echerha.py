import hashlib
import logging
import time
from uuid import UUID

import httpx

from .config import settings
from .models import WorkloadResponse

log = logging.getLogger(__name__)

# Гостьовий контракт офіційного web-клієнта (v5). X-User-Agent і device-заголовки
# додаються динамічно у fetch_workload з конфігу.
REQUIRED_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "X-Client-Locale": "uk",
}

# Option A: 1–120 друкованих ASCII-символів. Non-ASCII як байти HTTP-заголовка
# ненадійні між реалізаціями, тож fail-closed, а не «якось закодувати».
_DEVICE_NAME_MAX = 120


def _canonical_device_id(raw: str) -> str:
    """Canonical (lowercase) UUID-рядок або ValueError.

    Політика: parseable UUID обов'язковий; nil відхиляється (граматично валідний,
    але не називає жодного пристрою); без обмеження версії/варіанта — оператор
    кладе будь-який реальний persistent UUID. Канонізуємо через str(UUID(...)),
    щоб {фігурні}, ВЕРХНІЙ регістр і urn: зводились до одного вигляду.
    """
    try:
        parsed = UUID(raw)
    except (ValueError, TypeError, AttributeError):
        raise ValueError(
            "configuration: ECHERHA_DEVICE_ID must be a valid non-nil UUID"
        ) from None
    if parsed.int == 0:
        raise ValueError("configuration: ECHERHA_DEVICE_ID must be a valid non-nil UUID")
    return str(parsed)


def _validated_device_name(name: str) -> str:
    """1–120 друкованих ASCII (0x20–0x7E) або ValueError. Fail-closed на порожнє,
    Unicode, control-символи (вкл. \\n, \\t), DEL і довші за 120."""
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


async def fetch_workload(client: httpx.AsyncClient) -> FetchResult:
    """Один запит до єЧерги.

    Помилки джерела не є нашою аварією: повертаємо їх як результат, щоб цикл
    записав причину і спокійно дочекався наступної хвилини.
    """
    # Fail-closed: некоректний device-конфіг не робить запиту взагалі — причина
    # йде в collector_runs.error, її бачить сторож. Назовні нічого не летить.
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

    # Тривалість міряємо власним монотонним таймером: httpx `.elapsed` доступний
    # лише в реальному networking-шляху (під тестовим транспортом його нема), а
    # duration_ms — це наша телеметрія, не частина дротового контракту.
    started = time.monotonic()
    try:
        request = client.build_request("GET", settings.workload_url, headers=headers)
        # httpx застосовує cookie jar і дефолтні заголовки клієнта на build_request,
        # тож знімаємо Authorization/Cookie ПІСЛЯ побудови — це покриває і успадковані
        # заголовки, і replay Set-Cookie з попереднього циклу. auth=None не дає
        # клієнтському auth повторно їх додати. Жодного ambient session state.
        request.headers.pop("Authorization", None)
        request.headers.pop("Cookie", None)
        r = await client.send(request, auth=None)
    except httpx.HTTPError as exc:
        log.warning("запит до єЧерги не вдався: %s", exc)
        return FetchResult(None, None, 0, None, str(exc))
    duration_ms = int((time.monotonic() - started) * 1000)

    if r.status_code != 200:
        log.warning("єЧерга відповіла %s", r.status_code)
        return FetchResult(None, r.status_code, duration_ms, None, f"HTTP {r.status_code}")

    body_sha256 = hashlib.sha256(r.content).hexdigest()
    try:
        parsed = WorkloadResponse.model_validate(r.json())
    except ValueError as exc:
        log.error("не вдалося розібрати відповідь: %s", exc)
        return FetchResult(None, r.status_code, duration_ms, body_sha256, f"parse: {exc}")

    return FetchResult(parsed, r.status_code, duration_ms, body_sha256, None)
