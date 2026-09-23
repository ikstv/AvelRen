"""Sending pushes via FCM HTTP v1.

We send **data** messages, not `notification`. The difference is fundamental: if
you send `notification`, the system itself draws the notification, and the app
cannot make it non-dismissable. We need our own — with `setOngoing`, sound, and
a single "OK" button.
"""

import asyncio
import logging
from typing import Any

import httpx
from google.auth.transport.requests import Request
from google.oauth2 import service_account

from .config import settings

log = logging.getLogger("avelren.fcm")

SCOPE = "https://www.googleapis.com/auth/firebase.messaging"

FCM_ERROR_DETAIL_TYPE = "type.googleapis.com/google.firebase.fcm.v1.FcmError"

# Only the FCM-specific UNREGISTERED unambiguously proves the token no longer
# exists. A top-level INVALID_ARGUMENT may describe a payload error, and
# SENDER_ID_MISMATCH — configuration/ownership; neither signal can be
# destructive.
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
            raise RuntimeError("FCM_CREDENTIALS_PATH is not set")
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
    """Sends a single message. Raises FcmError if it did not work.

    `ttl` and `collapse_key` are not options but a requirement for time-based
    alerts (audit R-04): without them FCM holds a message for up to four weeks,
    and a phone returning from offline would get a batch of stale repeats about
    a queue that no longer exists. With collapse_key an offline device gets ONE,
    the latest.
    """
    # _creds() may do a synchronous OAuth token refresh (network round-trip to
    # Google) when the cached token expires. Run it in a worker thread so it
    # never blocks the event loop and stalls other in-flight notifications/API
    # requests (audit H-1).
    creds, project_id = await asyncio.to_thread(_creds)

    android: dict[str, Any] = {
        # High priority wakes a sleeping device — without it a queue
        # notification would arrive an hour late.
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
    # All values as strings: FCM accepts only strings in data.
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
    """Cancelling an already-shown notification (A-02).

    `kind` here is the alert type (threshold|eta), not the message type: the
    phone derives from it the same notification id as for the original, and
    dismisses it. The same collapse_key as the original push, so the cancel
    supersedes any undelivered repeat.

    IMPORTANT: the id lives in `cancel_alert_id`, NOT in the legacy field
    `alert_id`. The old client (baseline c7d2e1f) does not know type=cancel and
    would treat any non-health push with `alert_id` as a regular alert — it would
    show a new ongoing notification instead of dismissing. Without `alert_id` it
    reaches `data["alert_id"] ?: return` and silently ignores the cancel.
    Collapse_key still evicts the queued normal push. (audit A-02 / B1)
    """
    return {
        "type": "cancel",
        "kind": kind,
        "cancel_alert_id": str(alert_id),
    }
