"""Behavioral contract for fail-safe FCM HTTP v1 error handling."""

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from avelren import fcm


FCM_DETAIL_TYPE = "type.googleapis.com/google.firebase.fcm.v1.FcmError"


def _response(status_code: int, error: dict | None = None, text: str | None = None):
    async def handler(request: httpx.Request) -> httpx.Response:
        if error is not None:
            return httpx.Response(status_code, json={"error": error}, request=request)
        return httpx.Response(status_code, text=text or "", request=request)

    return handler


def _send(monkeypatch, handler) -> None:
    monkeypatch.setattr(
        fcm,
        "_creds",
        lambda: (SimpleNamespace(token="access-token"), "test-project"),
    )

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await fcm.send(client, "device-token", {"type": "test"})

    asyncio.run(run())


def _error(monkeypatch, status_code: int, error: dict) -> fcm.FcmError:
    with pytest.raises(fcm.FcmError) as raised:
        _send(monkeypatch, _response(status_code, error=error))
    return raised.value


def test_http_200_is_success(monkeypatch):
    _send(monkeypatch, _response(200, error={"unexpected": "ignored"}))


def test_invalid_argument_with_bad_request_detail_is_not_dead(monkeypatch):
    exc = _error(
        monkeypatch,
        400,
        {
            "status": "INVALID_ARGUMENT",
            "message": "Invalid value at message.data",
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.BadRequest",
                    "fieldViolations": [{"field": "message.data"}],
                }
            ],
        },
    )

    assert exc.canonical_status == "INVALID_ARGUMENT"
    assert exc.fcm_error_code is None
    assert exc.dead_token is False
    assert exc.retryable is False


def test_invalid_argument_with_fcm_detail_is_conservatively_not_dead(monkeypatch):
    exc = _error(
        monkeypatch,
        400,
        {
            "status": "INVALID_ARGUMENT",
            "message": "Invalid registration token",
            "details": [{"@type": FCM_DETAIL_TYPE, "errorCode": "INVALID_ARGUMENT"}],
        },
    )

    assert exc.fcm_error_code == "INVALID_ARGUMENT"
    assert exc.dead_token is False


def test_fcm_unregistered_is_confirmed_dead_token(monkeypatch):
    exc = _error(
        monkeypatch,
        404,
        {
            "status": "NOT_FOUND",
            "message": "Requested entity was not found.",
            "details": [{"@type": FCM_DETAIL_TYPE, "errorCode": "UNREGISTERED"}],
        },
    )

    assert exc.http_status == 404
    assert exc.canonical_status == "NOT_FOUND"
    assert exc.fcm_error_code == "UNREGISTERED"
    assert exc.dead_token is True
    assert exc.retryable is False


def test_sender_id_mismatch_does_not_disable_token(monkeypatch):
    exc = _error(
        monkeypatch,
        403,
        {
            "status": "PERMISSION_DENIED",
            "message": "Sender ID mismatch",
            "details": [{"@type": FCM_DETAIL_TYPE, "errorCode": "SENDER_ID_MISMATCH"}],
        },
    )

    assert exc.fcm_error_code == "SENDER_ID_MISMATCH"
    assert exc.dead_token is False
    assert exc.retryable is False


@pytest.mark.parametrize(
    ("http_status", "canonical_status", "fcm_error_code"),
    [
        (429, "RESOURCE_EXHAUSTED", "QUOTA_EXCEEDED"),
        (503, "UNAVAILABLE", "UNAVAILABLE"),
        (500, "INTERNAL", "INTERNAL"),
    ],
)
def test_transient_fcm_errors_are_retryable(
    monkeypatch, http_status, canonical_status, fcm_error_code
):
    exc = _error(
        monkeypatch,
        http_status,
        {
            "status": canonical_status,
            "message": "temporary",
            "details": [{"@type": FCM_DETAIL_TYPE, "errorCode": fcm_error_code}],
        },
    )

    assert exc.dead_token is False
    assert exc.retryable is True


def test_non_json_response_preserves_token(monkeypatch):
    with pytest.raises(fcm.FcmError) as raised:
        _send(monkeypatch, _response(502, text="upstream returned HTML"))

    assert raised.value.http_status == 502
    assert raised.value.canonical_status == "502"
    assert raised.value.fcm_error_code is None
    assert raised.value.dead_token is False
    assert raised.value.retryable is True
