"""The enrollment path for `devices.is_admin` (#112).

The column decides who the watchdog can reach. It had readers everywhere and no
writer anywhere, so it was filled — or not filled — by hand. These tests pin the
two things that made the hand-written version dangerous: that a promotion with no
FCM token is called out rather than counted as success, and that the number
reported as "the channel" is the number of devices an alert can actually reach.
"""

import uuid

import pytest

from avelren import admin_enroll


def _is_admin(conn, device_id: str) -> bool:
    return conn.execute(
        "SELECT is_admin FROM devices WHERE id = %s", (device_id,)
    ).fetchone()["is_admin"]


def _plain_device(conn, *, token: str | None) -> str:
    row = conn.execute(
        "INSERT INTO devices (fcm_token) VALUES (%s) RETURNING id", (token,)
    ).fetchone()
    return str(row["id"])


def test_promotes_a_device(conn, device):
    assert admin_enroll.set_admin(conn, device.device_id, admin=True) == 0
    assert _is_admin(conn, device.device_id) is True


def test_revokes_a_device(conn, device):
    admin_enroll.set_admin(conn, device.device_id, admin=True)

    assert admin_enroll.set_admin(conn, device.device_id, admin=False) == 0
    assert _is_admin(conn, device.device_id) is False


def test_unknown_device_is_reported_not_crashed(conn):
    """A typo in a UUID must be an error message, not a traceback — this is run
    against production by hand, and a traceback there reads as "it half worked"."""
    assert admin_enroll.set_admin(conn, str(uuid.uuid4()), admin=True) == 1


def test_channel_counts_only_admins_that_can_be_reached(conn):
    """The measurement that matters, and the one the old hand-written UPDATE hid.

    Production today has one admin and zero admins with a token: `is_admin` alone
    reports a healthy channel in exactly the state where nothing can be delivered.
    """
    before = admin_enroll._channel_size(conn)

    tokenless = _plain_device(conn, token=None)
    with_token = _plain_device(conn, token=f"tok-{uuid.uuid4()}")
    try:
        admin_enroll.set_admin(conn, tokenless, admin=True)
        assert admin_enroll._channel_size(conn) == before, (
            "an admin without a token is a subscriber to nothing and must not "
            "count towards the channel"
        )

        admin_enroll.set_admin(conn, with_token, admin=True)
        assert admin_enroll._channel_size(conn) == before + 1
    finally:
        conn.execute("DELETE FROM devices WHERE id = ANY(%s)", ([tokenless, with_token],))


def test_promotion_without_a_token_warns(conn, caplog):
    """Silence here would recreate the defect: the operator walks away believing
    the channel is armed, and finds out otherwise from the alert that never came."""
    tokenless = _plain_device(conn, token=None)
    try:
        with caplog.at_level("WARNING"):
            assert admin_enroll.set_admin(conn, tokenless, admin=True) == 0
        assert any("NO fcm_token" in r.getMessage() for r in caplog.records)
    finally:
        conn.execute("DELETE FROM devices WHERE id = %s", (tokenless,))


def test_cli_refuses_an_ambiguous_invocation():
    """Both a device id and --list, or neither, is a mistake worth stopping on
    rather than guessing at — the guess would either promote nothing or promote
    something the operator did not name."""
    with pytest.raises(SystemExit):
        admin_enroll.main([])
    with pytest.raises(SystemExit):
        admin_enroll.main(["--list", str(uuid.uuid4())])
