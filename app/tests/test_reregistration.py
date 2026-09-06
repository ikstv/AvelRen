"""What a re-registered installation takes with it (#174).

The app gets a new `device_id` whenever its storage is lost — a reinstall,
cleared data, a restore onto a new phone. Firebase hands back the same FCM token,
so for one request the server can see that the new row and an old one are the same
physical device. It used to see that and use it only to avoid violating
UNIQUE(fcm_token).

What that cost is not hypothetical. A threshold subscription stayed on a device
row abandoned on 2026-08-25; it kept firing alerts nobody could receive — five of
six over three weeks — and the app never showed it, because the app lists the
subscriptions of the current `device_id`. Invisible to the user, a success to the
server, and on 2026-09-06 it cost a real queue window at the border.
"""

import uuid
from datetime import UTC, datetime, timedelta


def _register(api_client, token: str) -> tuple[str, dict]:
    """A fresh installation, exactly as the app does it."""
    r = api_client.post("/devices", json={"fcm_token": token})
    assert r.status_code in (200, 201), r.text
    body = r.json()
    return body["device_id"], {
        "X-Device-Id": body["device_id"],
        "X-Device-Secret": body["device_secret"],
    }


def _claim_token(api_client, headers: dict, token: str) -> None:
    r = api_client.put("/devices/token", json={"fcm_token": token}, headers=headers)
    assert r.status_code == 200, r.text


def test_reregistration_carries_the_subscription_over(conn, checkpoint, api_client):
    """The defect itself: the alert the driver set up must follow the phone."""
    token = f"tok-{uuid.uuid4()}"
    old_id, old_headers = _register(api_client, token)

    r = api_client.post(
        "/subscriptions",
        json={"checkpoint_id": checkpoint, "threshold": 100},
        headers=old_headers,
    )
    assert r.status_code in (200, 201), r.text

    # The app is reinstalled: new identity, same Firebase token.
    new_id, new_headers = _register(api_client, f"tmp-{uuid.uuid4()}")
    _claim_token(api_client, new_headers, token)

    moved = conn.execute(
        "SELECT device_id FROM subscriptions WHERE checkpoint_id = %s", (checkpoint,)
    ).fetchone()
    assert str(moved["device_id"]) == new_id, "the subscription stayed on the dead row"

    # And it is visible again — the half of the failure the user could see.
    assert any(
        s["checkpoint_id"] == checkpoint
        for s in api_client.get("/subscriptions", headers=new_headers).json()
    )
    assert api_client.get("/subscriptions", headers=old_headers).json() == []
    conn.execute("DELETE FROM devices WHERE id = ANY(%s)", ([old_id, new_id],))


def test_reregistration_carries_the_eta_target_over(conn, checkpoint, api_client):
    token = f"tok-{uuid.uuid4()}"
    old_id, old_headers = _register(api_client, token)

    target_at = (datetime.now(UTC) + timedelta(hours=6)).replace(microsecond=0)
    r = api_client.post(
        "/eta-targets",
        json={"checkpoint_id": checkpoint, "target_at": target_at.isoformat()},
        headers=old_headers,
    )
    assert r.status_code in (200, 201), r.text

    new_id, new_headers = _register(api_client, f"tmp-{uuid.uuid4()}")
    _claim_token(api_client, new_headers, token)

    moved = conn.execute(
        "SELECT device_id FROM eta_targets WHERE checkpoint_id = %s AND is_active",
        (checkpoint,),
    ).fetchone()
    assert str(moved["device_id"]) == new_id
    conn.execute("DELETE FROM devices WHERE id = ANY(%s)", ([old_id, new_id],))


def test_a_duplicate_is_left_behind_instead_of_aborting_the_request(
    conn, checkpoint, api_client
):
    """The collision that would otherwise take the whole request down.

    Both tables carry a UNIQUE on (device_id, ...). If the new installation
    already has the same subscription, moving the old one would raise, roll back
    the transaction, and lose the token update the client is actually waiting for
    — turning a silent data problem into a loud delivery one.
    """
    token = f"tok-{uuid.uuid4()}"
    old_id, old_headers = _register(api_client, token)
    api_client.post(
        "/subscriptions",
        json={"checkpoint_id": checkpoint, "threshold": 100},
        headers=old_headers,
    )

    new_id, new_headers = _register(api_client, f"tmp-{uuid.uuid4()}")
    api_client.post(
        "/subscriptions",
        json={"checkpoint_id": checkpoint, "threshold": 100},
        headers=new_headers,
    )

    _claim_token(api_client, new_headers, token)  # must not 500

    rows = conn.execute(
        "SELECT device_id FROM subscriptions WHERE checkpoint_id = %s AND threshold = 100",
        (checkpoint,),
    ).fetchall()
    assert len(rows) == 2, "nothing was merged or deleted, only left in place"
    token_row = conn.execute(
        "SELECT fcm_token FROM devices WHERE id = %s", (new_id,)
    ).fetchone()
    assert token_row["fcm_token"] == token, "the token update itself must still land"
    conn.execute("DELETE FROM devices WHERE id = ANY(%s)", ([old_id, new_id],))


def test_a_plain_token_update_moves_nothing(conn, checkpoint, api_client, device):
    """No orphan, no migration. A device refreshing its own token must not become
    a way to hoover up rows that happen to be lying around."""
    other_id, other_headers = _register(api_client, f"tok-{uuid.uuid4()}")
    api_client.post(
        "/subscriptions",
        json={"checkpoint_id": checkpoint, "threshold": 100},
        headers=other_headers,
    )

    _claim_token(api_client, device.headers(), f"fresh-{uuid.uuid4()}")

    still = conn.execute(
        "SELECT device_id FROM subscriptions WHERE checkpoint_id = %s", (checkpoint,)
    ).fetchone()
    assert str(still["device_id"]) == other_id
    conn.execute("DELETE FROM devices WHERE id = %s", (other_id,))
