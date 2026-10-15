"""ACK лише прибирає локальне сповіщення до наступної успішної доставки."""

import pytest


def _threshold_alert(conn, device, checkpoint):
    subscription_id = conn.execute(
        "INSERT INTO subscriptions(device_id, checkpoint_id, threshold) "
        "VALUES(%s, %s, 50) RETURNING id",
        (device.device_id, checkpoint),
    ).fetchone()["id"]
    alert_id = conn.execute(
        "INSERT INTO alerts(subscription_id, checkpoint_id, threshold, vehicles_at_trigger) "
        "VALUES(%s, %s, 50, 80) RETURNING id",
        (subscription_id, checkpoint),
    ).fetchone()["id"]
    return alert_id, None


def _eta_alert(conn, device, checkpoint):
    target_id = conn.execute(
        "INSERT INTO eta_targets(device_id, checkpoint_id, target_at) "
        "VALUES(%s, %s, now() + interval '1 hour') RETURNING id",
        (device.device_id, checkpoint),
    ).fetchone()["id"]
    alert_id = conn.execute(
        "INSERT INTO eta_alerts(target_id, checkpoint_id, eta_at_trigger, "
        "wait_seconds_at_trigger) VALUES(%s, %s, now() + interval '1 hour', 3600) "
        "RETURNING id",
        (target_id, checkpoint),
    ).fetchone()["id"]
    return alert_id, target_id


@pytest.mark.parametrize(
    ("kind", "endpoint", "table", "create"),
    [
        ("threshold", "/alerts/{alert_id}/ack", "alerts", _threshold_alert),
        ("eta", "/eta-alerts/{alert_id}/ack", "eta_alerts", _eta_alert),
    ],
)
def test_ack_keeps_alert_pending_but_hides_it_until_resend(
    api_client, conn, checkpoint, device, kind, endpoint, table, create
):
    alert_id, target_id = create(conn, device, checkpoint)

    first = api_client.post(endpoint.format(alert_id=alert_id), headers=device.headers())
    assert first.status_code == 200
    assert first.json() == {"status": "acknowledged"}

    row = conn.execute(
        f"SELECT status, acknowledged_at, last_sent_at FROM {table} WHERE id=%s", (alert_id,)
    ).fetchone()
    assert row["status"] == "pending"
    assert row["acknowledged_at"] is not None
    assert row["last_sent_at"] is None
    if target_id is not None:
        target = conn.execute(
            "SELECT is_active FROM eta_targets WHERE id=%s", (target_id,)
        ).fetchone()
        assert target["is_active"]

    # The foreground reconciler must not recreate the just-dismissed notification.
    assert alert_id not in api_client.get("/active-alerts", headers=device.headers()).json()[kind]

    acknowledged_at = row["acknowledged_at"]
    repeated = api_client.post(endpoint.format(alert_id=alert_id), headers=device.headers())
    assert repeated.status_code == 200
    assert repeated.json() == {"status": "acknowledged"}
    assert conn.execute(
        f"SELECT acknowledged_at FROM {table} WHERE id=%s", (alert_id,)
    ).fetchone()["acknowledged_at"] == acknowledged_at


@pytest.mark.parametrize(
    ("kind", "endpoint", "table", "create"),
    [
        ("threshold", "/alerts/{alert_id}/ack", "alerts", _threshold_alert),
        ("eta", "/eta-alerts/{alert_id}/ack", "eta_alerts", _eta_alert),
    ],
)
def test_ack_dismisses_each_successful_resend(
    api_client, conn, checkpoint, device, kind, endpoint, table, create
):
    alert_id, _ = create(conn, device, checkpoint)
    url = endpoint.format(alert_id=alert_id)
    headers = device.headers()
    assert api_client.post(url, headers=headers).status_code == 200

    for _ in range(2):
        conn.execute(
            f"UPDATE {table} SET last_sent_at=clock_timestamp(), "
            "send_count=send_count+1 WHERE id=%s",
            (alert_id,),
        )
        assert alert_id in api_client.get("/active-alerts", headers=headers).json()[kind]

        assert api_client.post(url, headers=headers).status_code == 200
        row = conn.execute(
            f"SELECT status, acknowledged_at, last_sent_at FROM {table} WHERE id=%s",
            (alert_id,),
        ).fetchone()
        assert row["status"] == "pending"
        assert row["acknowledged_at"] >= row["last_sent_at"]
        assert alert_id not in api_client.get("/active-alerts", headers=headers).json()[kind]

        # A duplicate acknowledgement of this delivery remains idempotent.
        assert api_client.post(url, headers=headers).status_code == 200
        assert conn.execute(
            f"SELECT acknowledged_at FROM {table} WHERE id=%s", (alert_id,)
        ).fetchone()["acknowledged_at"] == row["acknowledged_at"]


@pytest.mark.parametrize(
    ("kind", "endpoint", "table", "create"),
    [
        ("threshold", "/subscriptions/{owner_id}", "alerts", _threshold_alert),
        ("eta", "/eta-targets/{owner_id}", "eta_alerts", _eta_alert),
    ],
)
def test_manual_delete_is_the_terminal_alert_transition(
    api_client, conn, checkpoint, device, kind, endpoint, table, create
):
    alert_id, owner_id = create(conn, device, checkpoint)
    if owner_id is None:
        owner_id = conn.execute(
            "SELECT subscription_id FROM alerts WHERE id=%s", (alert_id,)
        ).fetchone()["subscription_id"]

    deleted = api_client.delete(endpoint.format(owner_id=owner_id), headers=device.headers())
    assert deleted.status_code == 204
    assert conn.execute(f"SELECT 1 FROM {table} WHERE id=%s", (alert_id,)).fetchone() is None
    cancel = conn.execute(
        "SELECT kind, alert_id, device_id FROM notification_cancels WHERE kind=%s AND alert_id=%s",
        (kind, alert_id),
    ).fetchone()
    assert cancel["kind"] == kind
    assert cancel["alert_id"] == alert_id
    assert str(cancel["device_id"]) == device.device_id
