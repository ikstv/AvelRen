"""Регресія для AUTH-1 і сусідніх знахідок аудиту (API-1, API-3).

Основне твердження: FCM-токен НЕ є credential. Знання чужого токена не
повинно давати доступ до чужих підписок навіть якщо застосунок повторно
викликає POST /devices з цим токеном.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch


def test_repeat_registration_with_known_token_does_not_leak_device_id(
    conn, checkpoint, api_client
):
    """Ядро AUTH-1.

    Атакувальник знає FCM-токен жертви (він живе на клієнті, в логах Google,
    у крешах). До виправлення `POST /devices {fcm_token}` повертав існуючий
    device_id жертви — і атака була завершена. Тепер повторна реєстрація
    завжди створює нову installation з новою парою `(id, secret)`; чужі
    підписки лишаються недосяжними.
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

    # Атакувальник, знаючи той самий FCM-токен, викликає POST /devices.
    attacker = api_client.post("/devices", json={"fcm_token": token})
    assert attacker.status_code == 201
    attacker_id = attacker.json()["device_id"]
    attacker_secret = attacker.json()["device_secret"]
    assert attacker_id != victim_id, "різні installation мають різні id"

    # Атакувальник читає СВОЇ підписки — вони порожні.
    own = api_client.get(
        "/subscriptions",
        headers={"X-Device-Id": attacker_id, "X-Device-Secret": attacker_secret},
    )
    assert own.status_code == 200
    assert own.json() == []

    # А з чужим id, але своїм secret — 401 (secret не підходить під чужий hash).
    # Не 403 — не даємо оракул на існування id.
    forged = api_client.get(
        "/subscriptions",
        headers={"X-Device-Id": victim_id, "X-Device-Secret": attacker_secret},
    )
    assert forged.status_code == 401


def test_state_changing_endpoints_require_secret(checkpoint, device, api_client):
    """Мінімум: жоден endpoint, що змінює стан, не приймає одного X-Device-Id."""
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
    """Синтаксична помилка в X-Device-Id — це помилка клієнта (400), не
    падіння сервера (500) і не «БД лежить» (503)."""
    r = api_client.get(
        "/subscriptions",
        headers={"X-Device-Id": "not-a-uuid", "X-Device-Secret": device.device_secret},
    )
    assert r.status_code == 400


def test_stale_installation_returns_401_and_reregistration_works(conn, device, api_client):
    """NEW-AUTH-2 регресія — контракт «401 → перереєструватись».

    Імітуємо ефект DB restore: рядок `devices` зник, а клієнт усе ще має
    старі headers. Сервер має повернути 401 (а не 500 і не 400), щоб Android
    міг спрацювати clearCredentials + registerDevice. Другий крок — новий
    POST /devices повертає свіжу пару, і вона одразу авторизує API-виклики.
    """
    stale_headers = device.headers()

    # Ефект DB restore: рядка більше немає.
    conn.execute("DELETE FROM devices WHERE id = %s", (device.device_id,))

    r = api_client.get("/subscriptions", headers=stale_headers)
    assert r.status_code == 401, "мертва installation мусить давати 401, не 400/500"

    # Клієнт очищає credentials і реєструється знову.
    reg = api_client.post("/devices", json={"fcm_token": "recovered-token-32chars-abcdefgh"})
    assert reg.status_code == 201
    new_id = reg.json()["device_id"]
    new_secret = reg.json()["device_secret"]
    assert new_id != device.device_id

    # Свіжа пара одразу авторизує захищений виклик.
    r = api_client.get(
        "/subscriptions",
        headers={"X-Device-Id": new_id, "X-Device-Secret": new_secret},
    )
    assert r.status_code == 200


def test_db_outage_after_select_is_503_not_500(device, api_client):
    """API-1 регресія — раніше `UPDATE devices SET last_seen` виконувався поза
    `try/except OperationalError`, тож падіння БД між SELECT (перевірка
    secret) і UPDATE давало необроблений 500 замість 503."""
    from psycopg import AsyncConnection, OperationalError

    original = AsyncConnection.execute

    async def flaky(self, query, params=None, *args, **kwargs):
        if "UPDATE devices SET last_seen" in str(query):
            raise OperationalError("simulated: connection lost between SELECT and UPDATE")
        return await original(self, query, params, *args, **kwargs)

    with patch.object(AsyncConnection, "execute", flaky):
        r = api_client.get("/subscriptions", headers=device.headers())

    assert r.status_code == 503, (
        f"падіння БД між SELECT і UPDATE мусить бути 503, отримали {r.status_code}"
    )


def test_naive_target_at_is_422_not_500(device, api_client):
    """API-3: раніше naive datetime доходив до порівняння з aware now() і
    падав у 500. Pydantic AwareDatetime тепер повертає 422 до виклику."""
    r = api_client.post(
        "/eta-targets",
        # Без offset — саме той сценарій, який раніше падав.
        json={"checkpoint_id": 1, "target_at": "2099-01-01T22:15:00"},
        headers=device.headers(),
    )
    assert r.status_code == 422
