"""Надсилання пушів через FCM HTTP v1.

Шлемо **data**-повідомлення, а не `notification`. Різниця принципова: якщо
віддати `notification`, сповіщення малює сама система, і застосунок не може
зробити його незникаючим. Нам потрібне своє — з `setOngoing`, звуком і
єдиною кнопкою «ОК».
"""

import logging
from typing import Any

import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from .config import settings

log = logging.getLogger("avelren.fcm")

SCOPE = "https://www.googleapis.com/auth/firebase.messaging"

FCM_ERROR_DETAIL_TYPE = "type.googleapis.com/google.firebase.fcm.v1.FcmError"

# Лише FCM-specific UNREGISTERED однозначно доводить, що token більше не
# існує. Top-level INVALID_ARGUMENT може описувати помилку payload, а
# SENDER_ID_MISMATCH — конфігурацію/ownership; обидва сигнали destructive бути
# не можуть.
CONFIRMED_DEAD_TOKEN_ERRORS = {"UNREGISTERED"}
RETRYABLE_FCM_ERRORS = {"QUOTA_EXCEEDED", "UNAVAILABLE", "INTERNAL"}
RETRYABLE_CANONICAL_STATUSES = {"RESOURCE_EXHAUSTED", "UNAVAILABLE", "INTERNAL"}


class FcmError(Exception):
    def __init__(
        self,
        *,
        http_status: int,
        canonical_status: str,
        fcm_error_code: str | None,
        message: str,
        dead_token: bool,
        retryable: bool,
    ) -> None:
        label = fcm_error_code or canonical_status
        super().__init__(f"{label}: {message}")
        self.http_status = http_status
        self.canonical_status = canonical_status
        # Backward-compatible alias for callers/logging that used the old
        # top-level-only model.
        self.status = canonical_status
        self.fcm_error_code = fcm_error_code
        self.dead_token = dead_token
        self.retryable = retryable


def _error_from_response(response: httpx.Response) -> FcmError:
    canonical_status = str(response.status_code)
    fcm_error_code: str | None = None
    message = response.text[:200]

    try:
        payload = response.json()
    except ValueError:
        payload = None

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            status_value = error.get("status")
            if isinstance(status_value, str):
                canonical_status = status_value

            message_value = error.get("message")
            if isinstance(message_value, str):
                message = message_value

            details = error.get("details")
            if isinstance(details, list):
                for detail in details:
                    if not isinstance(detail, dict):
                        continue
                    if detail.get("@type") != FCM_ERROR_DETAIL_TYPE:
                        continue
                    error_code = detail.get("errorCode")
                    if isinstance(error_code, str):
                        fcm_error_code = error_code
                        break

    dead_token = fcm_error_code in CONFIRMED_DEAD_TOKEN_ERRORS
    retryable = not dead_token and (
        fcm_error_code in RETRYABLE_FCM_ERRORS
        or canonical_status in RETRYABLE_CANONICAL_STATUSES
        or response.status_code == 429
        or response.status_code >= 500
    )
    return FcmError(
        http_status=response.status_code,
        canonical_status=canonical_status,
        fcm_error_code=fcm_error_code,
        message=message,
        dead_token=dead_token,
        retryable=retryable,
    )


_credentials: service_account.Credentials | None = None
_project_id: str | None = None


def _creds() -> tuple[service_account.Credentials, str]:
    global _credentials, _project_id
    if _credentials is None:
        if not settings.fcm_credentials_path:
            raise RuntimeError("FCM_CREDENTIALS_PATH не задано")
        _credentials = service_account.Credentials.from_service_account_file(
            settings.fcm_credentials_path, scopes=[SCOPE]
        )
        _project_id = _credentials.project_id
    if not _credentials.valid:
        _credentials.refresh(Request())
    return _credentials, _project_id  # type: ignore[return-value]


async def send(
    client: httpx.AsyncClient,
    token: str,
    data: dict[str, str],
    collapse_key: str | None = None,
    ttl_seconds: int = 600,
) -> None:
    """Надсилає одне повідомлення. Кидає FcmError, якщо не вийшло.

    `ttl` і `collapse_key` — не опції, а вимога до часових алертів (аудит R-04):
    без них FCM тримає повідомлення до чотирьох тижнів, і телефон, що
    повернувся з офлайну, отримав би пачку протухлих повторів про чергу, якої
    вже немає. З collapse_key офлайн-пристрій отримує ОДНЕ, останнє.
    """
    creds, project_id = _creds()

    android: dict[str, Any] = {
        # Високий пріоритет будить пристрій у режимі сну — без цього
        # сповіщення про чергу прийшло б із запізненням на годину.
        "priority": "high",
        "ttl": f"{ttl_seconds}s",
    }
    if collapse_key:
        android["collapse_key"] = collapse_key

    payload: dict[str, Any] = {
        "message": {
            "token": token,
            "data": data,
            "android": android,
        }
    }

    r = await client.post(
        f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send",
        headers={"Authorization": f"Bearer {creds.token}"},
        json=payload,
    )

    if r.status_code == 200:
        return

    raise _error_from_response(r)


def threshold_payload(alert_id: int, title: str, threshold: int, vehicles: int) -> dict[str, str]:
    # Усі значення рядками: FCM приймає в data лише рядки.
    return {
        "type": "threshold",
        "alert_id": str(alert_id),
        "checkpoint": title,
        "threshold": str(threshold),
        "vehicles": str(vehicles),
        "title": "Черга зросла",
        "body": f"{title}: {vehicles} авто, поріг {threshold}",
    }


def eta_payload(alert_id: int, title: str, eta_local: str) -> dict[str, str]:
    return {
        "type": "eta",
        "alert_id": str(alert_id),
        "checkpoint": title,
        "eta": eta_local,
        "title": "Час реєструватися",
        "body": f"{title}: зареєструйся зараз — в'їзд орієнтовно {eta_local}",
    }


def cancel_payload(kind: str, alert_id: int) -> dict[str, str]:
    """Скасування вже показаної нотифікації (A-02).

    `kind` тут — тип алерта (threshold|eta), а не тип повідомлення: телефон
    рахує з нього той самий notification id, що й для оригіналу, і гасить його.
    Той самий collapse_key, що й у оригінального push, тож cancel заміщує
    будь-який недоставлений повтор.

    ВАЖЛИВО: id лежить у `cancel_alert_id`, а НЕ у legacy-полі `alert_id`.
    Старий клієнт (baseline c7d2e1f) не знає type=cancel і трактував би
    будь-який non-health push із `alert_id` як звичайну тривогу — показав би
    нову ongoing-нотифікацію замість гасіння. Без `alert_id` він доходить до
    `data["alert_id"] ?: return` і мовчки ігнорує cancel. Collapse_key усе одно
    витісняє queued normal push. (аудит A-02 / B1)
    """
    return {
        "type": "cancel",
        "kind": kind,
        "cancel_alert_id": str(alert_id),
    }
