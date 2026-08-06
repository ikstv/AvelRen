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

# Токен більше не існує: застосунок видалено, дані очищено, токен протух.
# Далі слати марно — пристрій треба гасити.
DEAD_TOKEN_ERRORS = {"UNREGISTERED", "INVALID_ARGUMENT", "SENDER_ID_MISMATCH"}


class FcmError(Exception):
    def __init__(self, status: str, message: str, dead_token: bool) -> None:
        super().__init__(f"{status}: {message}")
        self.status = status
        self.dead_token = dead_token


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


async def send(client: httpx.AsyncClient, token: str, data: dict[str, str]) -> None:
    """Надсилає одне повідомлення. Кидає FcmError, якщо не вийшло."""
    creds, project_id = _creds()

    payload: dict[str, Any] = {
        "message": {
            "token": token,
            "data": data,
            "android": {
                # Високий пріоритет будить пристрій у режимі сну — без цього
                # сповіщення про чергу прийшло б із запізненням на годину.
                "priority": "high",
            },
        }
    }

    r = await client.post(
        f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send",
        headers={"Authorization": f"Bearer {creds.token}"},
        json=payload,
    )

    if r.status_code == 200:
        return

    try:
        err = r.json().get("error", {})
        status = err.get("status", str(r.status_code))
        message = err.get("message", r.text[:200])
    except ValueError:
        status, message = str(r.status_code), r.text[:200]

    raise FcmError(status, message, dead_token=status in DEAD_TOKEN_ERRORS)


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
