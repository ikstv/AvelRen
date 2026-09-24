"""Actual deletion, role boundaries, cascades and concurrent activity in isolation."""

import psycopg
import pytest


def test_retention_dry_run_and_cascade(database, conn, device, checkpoint):
    from avelren.device_retention import run

    conn.execute(
        "UPDATE devices SET last_seen=now()-interval '91 days' WHERE id=%s", (device.device_id,)
    )
    subscription = conn.execute(
        "INSERT INTO subscriptions(device_id,checkpoint_id,threshold) "
        "VALUES (%s,%s,50) RETURNING id",
        (device.device_id, checkpoint),
    ).fetchone()["id"]
    conn.execute("INSERT INTO subscription_state(subscription_id) VALUES (%s)", (subscription,))
    conn.execute(
        "INSERT INTO alerts(subscription_id,checkpoint_id,threshold,vehicles_at_trigger) "
        "VALUES (%s,%s,50,40)",
        (subscription, checkpoint),
    )
    conn.execute(
        "UPDATE admin_access SET approved_device_id=%s WHERE singleton", (device.device_id,)
    )
    with psycopg.connect(database("notifier"), autocommit=True) as worker:
        report = run(worker)
        assert report["candidates"] == 1 and report["deleted"] == 0
        assert conn.execute("SELECT count(*) AS n FROM devices").fetchone()["n"] == 1
        report = run(worker, apply=True)
        assert report["deleted"] == 1 and report["remaining"] == 0
    for table in ("devices", "subscriptions", "subscription_state", "alerts"):
        assert conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"] == 0
    assert (
        conn.execute("SELECT approved_device_id FROM admin_access").fetchone()["approved_device_id"]
        is None
    )
    # Queue history/catalogue is independent of device identity.
    assert conn.execute("SELECT count(*) AS n FROM checkpoints").fetchone()["n"] == 1


def test_active_device_and_exact_90_day_boundary_survive(database, conn, device):
    with psycopg.connect(database("migrator")) as worker:
        worker.execute(
            "UPDATE devices SET last_seen=now()-interval '90 days' WHERE id=%s", (device.device_id,)
        )
        row = worker.execute("SELECT * FROM prune_inactive_devices(true)").fetchone()
        assert row == (0, 0)  # transaction_timestamp is stable within this transaction
    assert conn.execute("SELECT count(*) AS n FROM devices").fetchone()["n"] == 1


@pytest.mark.parametrize("role", ["api", "collector", "watchdog", "backup"])
def test_other_services_cannot_invoke_cleanup(database, role):
    with psycopg.connect(database(role), autocommit=True) as worker:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            worker.execute("SELECT * FROM prune_inactive_devices(true)")


def test_notifier_cannot_delete_arbitrary_devices(database):
    with psycopg.connect(database("notifier"), autocommit=True) as worker:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            worker.execute("DELETE FROM devices WHERE false")


def test_inflight_activity_is_not_deleted(database, conn, device):
    conn.execute(
        "UPDATE devices SET last_seen=now()-interval '91 days' WHERE id=%s", (device.device_id,)
    )
    with psycopg.connect(database("api")) as active:
        active.execute(
            "SELECT secret_hash FROM devices WHERE id=%s FOR UPDATE", (device.device_id,)
        )
        with psycopg.connect(database("notifier"), autocommit=True) as worker:
            assert worker.execute("SELECT * FROM prune_inactive_devices(true)").fetchone() == (1, 0)
        active.execute("UPDATE devices SET last_seen=now() WHERE id=%s", (device.device_id,))
    with psycopg.connect(database("notifier"), autocommit=True) as worker:
        assert worker.execute("SELECT * FROM prune_inactive_devices(true)").fetchone() == (0, 0)


def test_authenticated_activity_refreshes_old_installation(api_client, conn, device, database):
    conn.execute(
        "UPDATE devices SET last_seen=now()-interval '91 days' WHERE id=%s", (device.device_id,)
    )
    assert api_client.get("/subscriptions", headers=device.headers()).status_code == 200
    with psycopg.connect(database("notifier"), autocommit=True) as worker:
        assert worker.execute("SELECT * FROM prune_inactive_devices(true)").fetchone() == (0, 0)


def test_deleted_installation_gets_401_and_can_register_again(api_client, conn, device, database):
    conn.execute(
        "UPDATE devices SET last_seen=now()-interval '91 days' WHERE id=%s", (device.device_id,)
    )
    with psycopg.connect(database("notifier"), autocommit=True) as worker:
        worker.execute("SELECT * FROM prune_inactive_devices(true)")
    assert api_client.get("/subscriptions", headers=device.headers()).status_code == 401
    response = api_client.post("/devices", json={"fcm_token": "synthetic-reinstalled-token"})
    assert response.status_code == 201


def test_cleanup_is_batched_and_does_not_delete_active_devices(database, conn, device):
    from avelren.device_retention import run

    conn.execute(
        "INSERT INTO devices(last_seen) SELECT now()-interval '91 days' FROM generate_series(1,501)"
    )
    with psycopg.connect(database("notifier"), autocommit=True) as worker:
        result = run(worker, apply=True)
        assert result["candidates"] == 501
        assert result["deleted"] == 501 and result["remaining"] == 0
    assert conn.execute("SELECT count(*) AS n FROM devices").fetchone()["n"] == 1


def test_wrong_secret_does_not_extend_retention(api_client, conn, device, database):
    conn.execute(
        "UPDATE devices SET last_seen=now()-interval '91 days' WHERE id=%s", (device.device_id,)
    )
    headers = {**device.headers(), "X-Device-Secret": "invalid"}
    assert api_client.get("/subscriptions", headers=headers).status_code == 401
    with psycopg.connect(database("notifier"), autocommit=True) as worker:
        assert worker.execute("SELECT * FROM prune_inactive_devices(true)").fetchone() == (1, 1)
