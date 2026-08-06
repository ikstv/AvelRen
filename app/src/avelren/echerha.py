import hashlib
import logging

import httpx

from .config import settings
from .models import WorkloadResponse

log = logging.getLogger(__name__)

# Без цих двох заголовків сервіс відповідає 403.
REQUIRED_HEADERS = {
    "Accept": "application/json",
    "X-Client-Locale": "uk",
    "X-User-Agent": "UABorder/1.0.0 Web/1.1.0 User/guest",
}


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
    headers = {**REQUIRED_HEADERS, "User-Agent": settings.user_agent}
    try:
        r = await client.get(settings.workload_url, headers=headers)
        duration_ms = int(r.elapsed.total_seconds() * 1000)
    except httpx.HTTPError as exc:
        log.warning("запит до єЧерги не вдався: %s", exc)
        return FetchResult(None, None, 0, None, str(exc))

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
