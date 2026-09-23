"""Regression for AUTH-1 and neighboring audit findings (API-1, API-3).

The core claim: an FCM token is NOT a credential. Knowing someone else's token
must not grant access to their subscriptions, even if the app re-calls
POST /devices with that token.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch


def test_repeat_registration_with_known_token_does_not_leak_device_id(
    conn, checkpoint, api_client
):
    """The core of AUTH-1.

    The attacker knows the victim's FCM token (it lives on the client, in Google's
    logs, in crashes). Before the fix, `POST /devices {fcm_token}` returned the
    victim's existing device_id — and the attack was complete. Now a repeated
    registration always creates a new installation with a new `(id, secret)` pair;
    someone else's subscriptions stay out of reach.
    """
    token = "shared-fcm-token-32chars-abcdefgh"
    victim = api_client.post("/devices", json={"fcm_token": token})
    assert victim.status_code == 201
    victim_id = victim.json()["device_id"]
    victim_secret = victim.json()["device_secret"]

    sub = api_client.post(
        "/subscriptions",
        json={"checkpoint_id": checkpoint, "threshold": 50},
        headers={"X-Device-Id": victim_id, "X-Device-Secret": victim_secret},
    )
    assert sub.status_code == 201

    # The attacker, knowing the same FCM token, calls POST /devices.
    attacker = api_client.post("/devices", json={"fcm_token": token})
    assert attacker.status_code == 201
    attacker_id = attacker.json()["device_id"]
    attacker_secret = attacker.json()["device_secret"]
    assert attacker_id != victim_id, "different installations have different ids"

    # The attacker reads THEIR OWN subscriptions — they are empty.
    own = api_client.get(
        "/subscriptions",
        headers={"X-Device-Id": attacker_id, "X-Device-Secret": attacker_secret},
    )
    assert own.status_code == 200
    assert own.json() == []

    # And with a foreign id but their own secret — 401 (the secret does not match
    # the foreign hash). Not 403 — we do not give an oracle for id existence.
    forged = api_client.get(
        "/subscriptions",
        headers={"X-Device-Id": victim_id, "X-Device-Secret": attacker_secret},
    )
    assert forged.status_code == 401


def test_state_changing_endpoints_require_secret(checkpoint, device, api_client):
    """The minimum: no state-changing endpoint accepts an X-Device-Id alone."""
    r = api_client.post(
        "/subscriptions",
        json={"checkpoint_id": checkpoint, "threshold": 50},
        headers={"X-Device-Id": device.device_id},
    )
    assert r.status_code == 401

    r = api_client.post(
        "/eta-targets",
        json={
            "checkpoint_id": checkpoint,
            "target_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
        },
        headers={"X-Device-Id": device.device_id},
    )
    assert r.status_code == 401

    r = api_client.put(
        "/devices/token",
        json={"fcm_token": "some-new-token-32chars-abcdefghij"},
        headers={"X-Device-Id": device.device_id},
    )
    assert r.status_code == 401


def test_invalid_uuid_is_400_not_500(device, api_client):
    """A syntax error in X-Device-Id is a client error (400), not a server crash
    (500) and not "DB is down" (503)."""
    r = api_client.get(
        "/subscriptions",
        headers={"X-Device-Id": "not-a-uuid", "X-Device-Secret": device.device_secret},
    )
    assert r.status_code == 400


def test_stale_installation_returns_401_and_reregistration_works(conn, device, api_client):
    """NEW-AUTH-2 regression — the "401 → re-register" contract.

    We simulate the effect of a DB restore: the `devices` row is gone, but the
    client still has the old headers. The server must return 401 (not 500 and not
    400), so Android can trigger clearCredentials + registerDevice. The second
    step — a new POST /devices returns a fresh pair, and it immediately authorizes
    API calls.
    """
    stale_headers = device.headers()

    # The effect of a DB restore: the row is no longer there.
    conn.execute("DELETE FROM devices WHERE id = %s", (device.device_id,))

    r = api_client.get("/subscriptions", headers=stale_headers)
    assert r.status_code == 401, "a dead installation must give 401, not 400/500"

    # The client clears credentials and registers again.
    reg = api_client.post("/devices", json={"fcm_token": "recovered-token-32chars-abcdefgh"})
    assert reg.status_code == 201
    new_id = reg.json()["device_id"]
    new_secret = reg.json()["device_secret"]
    assert new_id != device.device_id

    # The fresh pair immediately authorizes a protected call.
    r = api_client.get(
        "/subscriptions",
        headers={"X-Device-Id": new_id, "X-Device-Secret": new_secret},
    )
    assert r.status_code == 200


def test_db_outage_after_select_is_503_not_500(device, api_client):
    """API-1 regression — previously `UPDATE devices SET last_seen` ran outside
    the `try/except OperationalError`, so a DB failure between the SELECT (secret
    check) and the UPDATE gave an unhandled 500 instead of 503."""
    from psycopg import AsyncConnection, OperationalError

    original = AsyncConnection.execute

    async def flaky(self, query, params=None, *args, **kwargs):
        if "UPDATE devices SET last_seen" in str(query):
            raise OperationalError("simulated: connection lost between SELECT and UPDATE")
        return await original(self, query, params, *args, **kwargs)

    with patch.object(AsyncConnection, "execute", flaky):
        r = api_client.get("/subscriptions", headers=device.headers())

    assert r.status_code == 503, (
        f"a DB failure between SELECT and UPDATE must be 503, got {r.status_code}"
    )


def test_naive_target_at_is_422_not_500(device, api_client):
    """API-3: previously a naive datetime reached a comparison with an aware now()
    and crashed with 500. Pydantic AwareDatetime now returns 422 before the call."""
    r = api_client.post(
        "/eta-targets",
        # Without an offset — exactly the scenario that used to crash.
        json={"checkpoint_id": 1, "target_at": "2099-01-01T22:15:00"},
        headers=device.headers(),
    )
    assert r.status_code == 422
