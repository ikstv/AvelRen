"""Володіння токеном: справжні API-запити та PostgreSQL під avelren_api."""

import asyncio
import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor
from time import monotonic

import pytest
from psycopg import AsyncConnection
from psycopg.errors import CheckViolation, QueryCanceled, UniqueViolation

from avelren import subscriptions_api

TOKEN = "synthetic-private-fcm-token-ownership-0001"
OTHER = "synthetic-private-fcm-token-ownership-0002"
CONFLICT = {"detail": {"code": "fcm_token_conflict"}}


def snapshot(conn):
    """Відмова не повинна змінити delivery, credentials, підписки чи Admin."""
    return {
        "devices": conn.execute(
            "SELECT id, fcm_token, secret_hash, notification_capabilities, is_admin "
            "FROM devices ORDER BY id"
        ).fetchall(),
        "subscriptions": conn.execute("SELECT * FROM subscriptions ORDER BY id").fetchall(),
        "admin": conn.execute("SELECT * FROM admin_access").fetchall(),
    }


def claim(conn, device, token):
    conn.execute("UPDATE devices SET fcm_token=%s WHERE id=%s", (token, device.device_id))


def assert_conflict(response):
    assert response.status_code == 409
    assert response.json() == CONFLICT


@pytest.mark.parametrize("legacy", [False, True])
def test_post_preserves_owner(conn, checkpoint, device, approved, api_client, legacy):
    claim(conn, device, TOKEN)
    conn.execute(
        "UPDATE devices SET is_admin=true, notification_capabilities=ARRAY['surge_v1'], "
        "last_seen=now()-interval '200 days' WHERE id=%s",
        (device.device_id,),
    )
    conn.execute(
        "INSERT INTO subscriptions(device_id,checkpoint_id,threshold) VALUES(%s,%s,50)",
        (device.device_id, checkpoint),
    )
    if legacy:
        conn.execute("UPDATE devices SET secret_hash=NULL WHERE id=%s", (device.device_id,))
    before = snapshot(conn)
    assert_conflict(api_client.post("/devices", json={"fcm_token": TOKEN}))
    assert snapshot(conn) == before


def test_put_preserves_both_devices(conn, checkpoint, device, installation, approved, api_client):
    other = installation()
    claim(conn, device, TOKEN)
    claim(conn, other, OTHER)
    conn.execute("UPDATE devices SET notification_capabilities=ARRAY['surge_v1']")
    conn.execute("UPDATE devices SET is_admin=true WHERE id=%s", (device.device_id,))
    for current in (device, other):
        conn.execute(
            "INSERT INTO subscriptions(device_id,checkpoint_id,threshold) VALUES(%s,%s,50)",
            (current.device_id, checkpoint),
        )
    before = snapshot(conn)
    assert_conflict(
        api_client.put("/devices/token", json={"fcm_token": TOKEN}, headers=other.headers())
    )
    assert snapshot(conn) == before
    for current in (device, other):
        response = api_client.get("/subscriptions", headers=current.headers())
        assert response.status_code == 200
        assert len(response.json()) == 1


@pytest.mark.parametrize("token", [None, TOKEN])
def test_own_or_free_token_success(conn, api_client, token):
    response = api_client.post("/devices", json={"fcm_token": token})
    assert response.status_code == 201
    credentials = response.json()
    assert set(credentials) == {"device_id", "device_secret"}
    headers = {
        "X-Device-Id": credentials["device_id"],
        "X-Device-Secret": credentials["device_secret"],
    }
    for candidate in (TOKEN, TOKEN, OTHER):
        response = api_client.put(
            "/devices/token",
            headers=headers,
            json={
                "fcm_token": candidate,
                "notification_capabilities": ["surge_v1"],
            },
        )
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        row = conn.execute("SELECT * FROM devices WHERE id=%s", (credentials["device_id"],))
        assert row.fetchone()["fcm_token"] == candidate
    assert snapshot(conn)["devices"][0]["notification_capabilities"] == ["surge_v1"]


def test_invalid_credentials_before_conflict(conn, device, api_client):
    claim(conn, device, TOKEN)
    before = snapshot(conn)
    headers = {**device.headers(), "X-Device-Secret": "wrong-synthetic-secret"}
    response = api_client.put("/devices/token", headers=headers, json={"fcm_token": TOKEN})
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid device credentials"}
    assert snapshot(conn) == before


def test_own_token_accepts_equivalent_uuid_header(conn, device, api_client):
    claim(conn, device, TOKEN)
    response = api_client.put(
        "/devices/token",
        json={"fcm_token": TOKEN},
        headers={
            **device.headers(),
            "X-Device-Id": device.device_id.upper(),
        },
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_deleted_after_auth401(conn, device, api_client, monkeypatch):
    authenticate = subscriptions_api._device

    async def delete_after_auth(*args):
        device_id = await authenticate(*args)
        await asyncio.to_thread(conn.execute, "DELETE FROM devices WHERE id=%s", (device_id,))
        return device_id

    monkeypatch.setattr(subscriptions_api, "_device", delete_after_auth)
    response = api_client.put("/devices/token", headers=device.headers(), json={"fcm_token": TOKEN})
    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid device credentials"}
    assert snapshot(conn)["devices"] == []


def race(monkeypatch, requests):
    """Зупиняємо обидва запити перед claim; SQL і транзакції залишаються справжніми."""
    execute = AsyncConnection.execute
    barrier = asyncio.Barrier(2)
    participants = set()

    async def synchronize(self, query, params=None, *args, **kwargs):
        text = str(query)
        if "pg_advisory_xact_lock" in text or "UPDATE devices SET fcm_token = NULL" in text:
            row = await (
                await execute(self, "SELECT current_user AS role, pg_backend_pid() AS pid")
            ).fetchone()
            participants.add((row["role"], row["pid"]))
            await asyncio.wait_for(barrier.wait(), timeout=5)
        return await execute(self, query, params, *args, **kwargs)

    monkeypatch.setattr(AsyncConnection, "execute", synchronize)
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(request) for request in requests]
        results = [future.result(timeout=15) for future in futures]
    assert len(participants) == 2
    assert {role for role, _ in participants} == {"avelren_api"}
    return results


def test_two_posts_one_owner(conn, api_client, monkeypatch):
    responses = race(
        monkeypatch,
        [
            lambda: api_client.post("/devices", json={"fcm_token": TOKEN}),
            lambda: api_client.post("/devices", json={"fcm_token": TOKEN}),
        ],
    )
    assert sorted(r.status_code for r in responses) == [201, 409]
    winner = next(r for r in responses if r.status_code == 201)
    assert_conflict(next(r for r in responses if r.status_code == 409))
    rows = snapshot(conn)["devices"]
    assert len(rows) == 1
    assert str(rows[0]["id"]) == winner.json()["device_id"]
    assert rows[0]["fcm_token"] == TOKEN


def test_post_vs_put(conn, device, api_client, monkeypatch):
    before = snapshot(conn)["devices"][0]
    post, put = race(
        monkeypatch,
        [
            lambda: api_client.post("/devices", json={"fcm_token": TOKEN}),
            lambda: api_client.put(
                "/devices/token", headers=device.headers(), json={"fcm_token": TOKEN}
            ),
        ],
    )
    assert (post.status_code, put.status_code) in {(201, 409), (409, 200)}
    assert_conflict(post if post.status_code == 409 else put)
    rows = snapshot(conn)["devices"]
    assert sum(row["fcm_token"] == TOKEN for row in rows) == 1
    own = next(row for row in rows if str(row["id"]) == device.device_id)
    if post.status_code == 201:
        assert own == before
    else:
        assert len(rows) == 1
        assert own["fcm_token"] == TOKEN


@pytest.mark.parametrize("cross_claim", [False, True])
def test_two_puts_no_deadlock(conn, device, installation, api_client, monkeypatch, cross_claim):
    other = installation()
    claim(conn, device, TOKEN)
    claim(conn, other, OTHER)
    before = snapshot(conn)
    first, second = (OTHER, TOKEN) if cross_claim else ("synthetic-new-free-token-0000000000",) * 2
    responses = race(
        monkeypatch,
        [
            lambda: api_client.put(
                "/devices/token", headers=device.headers(), json={"fcm_token": first}
            ),
            lambda: api_client.put(
                "/devices/token", headers=other.headers(), json={"fcm_token": second}
            ),
        ],
    )
    assert sorted(r.status_code for r in responses) == ([409, 409] if cross_claim else [200, 409])
    for response in responses:
        if response.status_code == 409:
            assert_conflict(response)
    after = snapshot(conn)
    if cross_claim:
        assert after == before
    else:
        assert sum(row["fcm_token"] == first for row in after["devices"]) == 1
        loser = device if responses[0].status_code == 409 else other
        assert next(r for r in after["devices"] if str(r["id"]) == loser.device_id) == next(
            r for r in before["devices"] if str(r["id"]) == loser.device_id
        )


@pytest.mark.parametrize("method", ["post", "put"])
def test_noncooperating_writer_unique_guard(
    conn, device, installation, api_client, monkeypatch, caplog, method
):
    other = installation()
    before = snapshot(conn)
    execute = AsyncConnection.execute
    injected = False

    async def claim_before_write(self, query, params=None, *args, **kwargs):
        nonlocal injected
        text = str(query)
        if not injected and (
            "INSERT INTO devices" in text or "UPDATE devices SET fcm_token = %s" in text
        ):
            injected = True
            await asyncio.to_thread(claim, conn, other, TOKEN)
        return await execute(self, query, params, *args, **kwargs)

    monkeypatch.setattr(AsyncConnection, "execute", claim_before_write)
    with caplog.at_level(logging.DEBUG):
        response = (
            api_client.post("/devices", json={"fcm_token": TOKEN})
            if method == "post"
            else api_client.put(
                "/devices/token", headers=device.headers(), json={"fcm_token": TOKEN}
            )
        )
    assert injected
    assert_conflict(response)
    after = snapshot(conn)
    for row in before["devices"]:
        if str(row["id"]) == other.device_id:
            row["fcm_token"] = TOKEN
    assert after == before
    for private in (
        TOKEN,
        device.device_id,
        device.device_secret,
        other.device_id,
        other.device_secret,
    ):
        assert private not in response.text
        assert private not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.parametrize("method", ["post", "put"])
def test_unrelated_integrity_error_propagates(conn, device, api_client, method):
    conn.execute(
        "ALTER TABLE devices ADD CONSTRAINT unrelated_token_check "
        "CHECK (fcm_token IS DISTINCT FROM 'synthetic-private-fcm-token-ownership-0001')"
    )
    before = snapshot(conn)
    with pytest.raises(CheckViolation):
        if method == "post":
            api_client.post("/devices", json={"fcm_token": TOKEN})
        else:
            api_client.put("/devices/token", headers=device.headers(), json={"fcm_token": TOKEN})
    assert snapshot(conn) == before


@pytest.mark.parametrize("method", ["post", "put"])
def test_unrelated_unique_error_propagates(conn, device, installation, api_client, method):
    other = installation()
    claim(conn, other, TOKEN + "-other")
    conn.execute("CREATE UNIQUE INDEX unrelated_token_prefix ON devices(left(fcm_token, 20))")
    before = snapshot(conn)
    with pytest.raises(UniqueViolation):
        if method == "post":
            api_client.post("/devices", json={"fcm_token": TOKEN})
        else:
            api_client.put("/devices/token", headers=device.headers(), json={"fcm_token": TOKEN})
    assert snapshot(conn) == before


@pytest.mark.parametrize("method", ["post", "put"])
def test_capabilities_failure_rolls_back_token(conn, device, api_client, method):
    conn.execute(
        "ALTER TABLE devices ADD CONSTRAINT no_new_capabilities "
        "CHECK (notification_capabilities='{}')"
    )
    before = snapshot(conn)
    body = {"fcm_token": TOKEN, "notification_capabilities": ["surge_v1"]}
    with pytest.raises(CheckViolation):
        if method == "post":
            api_client.post("/devices", json=body)
        else:
            api_client.put("/devices/token", headers=device.headers(), json=body)
    assert snapshot(conn) == before


def test_no_secret_diagnostics(api_client, monkeypatch, caplog):
    execute = AsyncConnection.execute
    secret = "synthetic-private-secret-never-log"

    async def timeout(self, query, params=None, *args, **kwargs):
        if "INSERT INTO devices" in str(query):
            raise QueryCanceled(f"sensitive SQL diagnostics: {TOKEN} {secret}")
        return await execute(self, query, params, *args, **kwargs)

    monkeypatch.setattr(AsyncConnection, "execute", timeout)
    with caplog.at_level(logging.WARNING):
        response = api_client.post("/devices", json={"fcm_token": TOKEN})
    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"
    assert "QueryCanceled" in caplog.text
    assert "57014" in caplog.text
    for private in (TOKEN, secret):
        assert private not in response.text
        assert private not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_token_lock_timeout_is_bounded503(conn, api_client, monkeypatch):
    # Незалежний writer тримає той самий стабільний lock до завершення HTTP.
    key = int.from_bytes(
        hashlib.sha256(b"avelren-fcm-token-v1" + TOKEN.encode()).digest()[:8], "big", signed=True
    )
    execute = AsyncConnection.execute

    async def short_timeout(self, query, params=None, *args, **kwargs):
        if "pg_advisory_xact_lock" in str(query):
            await execute(self, "SET LOCAL statement_timeout='150ms'")
        return await execute(self, query, params, *args, **kwargs)

    monkeypatch.setattr(AsyncConnection, "execute", short_timeout)
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (key,))
        start = monotonic()
        response = api_client.post("/devices", json={"fcm_token": TOKEN})
        elapsed = monotonic() - start
    assert response.status_code == 503
    assert elapsed < 3
    assert snapshot(conn)["devices"] == []
