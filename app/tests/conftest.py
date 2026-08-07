"""Спільне підґрунтя для тестів БД.

Дві вимоги, порушення яких коштувало б дорожче за самі тести.

1. **Тест не сміє торкнутися робочої БД.** Раніше `test_alerts.py` починався з
   `DELETE FROM alerts WHERE threshold = 50` — на проді це видалило б живі
   алерти реальних людей. Тому запуск тепер fail-closed: без явного
   `AVELREN_TEST_DB=1` і без тестової назви БД pytest завершується ДО першого
   запиту, а не «майже безпечно» щось видаляє.

2. **Чиста БД — нормальне середовище тесту.** Довідник пунктів наповнює
   збирач, тож на свіжих міграціях жодного checkpoint не існує. Тести більше
   не спираються на id 1 чи 5: кожен створює власний синтетичний пункт і
   прибирає лише свої записи.
"""

import asyncio
import os
import random
import secrets
import sys
from dataclasses import dataclass

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row


@dataclass(frozen=True)
class Installation:
    """Тестова installation: пара, з якою клієнт заходить у захищені ендпоінти."""

    device_id: str
    device_secret: str

    def headers(self) -> dict[str, str]:
        return {"X-Device-Id": self.device_id, "X-Device-Secret": self.device_secret}

DSN = os.environ.get("DATABASE_URL", "")

# Синтетичні id живуть заздалегідь у діапазоні, якого джерело не використовує:
# єЧерга видає невеликі числа, тож перетин із реальним довідником неможливий.
SYNTHETIC_ID_BASE = 900_000_000

# Windows за замовчуванням дає ProactorEventLoop, з яким psycopg в async-режимі
# не працює взагалі. Прод крутиться на Linux, але тести мають запускатися й на
# машині розробника — інакше єдиним способом їх прогнати лишається CI.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def pytest_configure(config: pytest.Config) -> None:
    """Запобіжник спрацьовує до збору тестів — тобто до будь-якого DELETE."""
    if not DSN:
        pytest.exit("DATABASE_URL не задано", returncode=3)

    if os.environ.get("AVELREN_TEST_DB") != "1":
        pytest.exit(
            "Тести змінюють БД. Потрібен явний AVELREN_TEST_DB=1 — "
            "щоб випадковий запуск не влучив у робочу базу.",
            returncode=3,
        )

    dbname = (conninfo_to_dict(DSN).get("dbname") or "").lower()
    if "test" not in dbname and "ci" not in dbname:
        pytest.exit(
            f"БД '{dbname}' не позначена як тестова. Назва має містити "
            "'test' або 'ci' — двох незалежних ознак достатньо, щоб "
            "потрапити в прод потрібно було саме намагатися.",
            returncode=3,
        )


@pytest.fixture()
def conn():
    """З'єднання без спільного стану між тестами."""
    with psycopg.connect(DSN, autocommit=True, row_factory=dict_row) as c:
        yield c


@pytest.fixture()
def checkpoint(conn) -> int:
    """Синтетичний пункт пропуску, який існує лише в межах одного тесту.

    Прибирання йде в порядку залежностей: пристрої каскадом знімають підписки,
    алерти й цілі, далі зникають спостереження й сам пункт. Нічого чужого
    тести не чіпають.
    """
    cid = SYNTHETIC_ID_BASE + random.randrange(1, 1_000_000)
    conn.execute(
        """
        INSERT INTO checkpoints (id, title, for_vehicle_type, country_name)
        VALUES (%s, %s, 1, 'test')
        """,
        (cid, f"synthetic-{cid}"),
    )
    try:
        yield cid
    finally:
        conn.execute(
            "DELETE FROM devices WHERE id IN ("
            "  SELECT device_id FROM subscriptions WHERE checkpoint_id = %s"
            "  UNION SELECT device_id FROM eta_targets WHERE checkpoint_id = %s)",
            (cid, cid),
        )
        conn.execute("DELETE FROM alerts WHERE checkpoint_id = %s", (cid,))
        conn.execute("DELETE FROM eta_alerts WHERE checkpoint_id = %s", (cid,))
        conn.execute("DELETE FROM observations WHERE checkpoint_id = %s", (cid,))
        conn.execute("DELETE FROM checkpoints WHERE id = %s", (cid,))


@pytest.fixture()
def api_client():
    """FastAPI TestClient з чистим пулом на кожен тест.

    `avelren.db._pool` — модульний singleton, і lifespan при закритті одного
    TestClient робить `pool.close()`. Наступний TestClient у тій самій сесії
    впав би на PoolClosed. Скидання _pool = None перед відкриттям гарантує
    новий пул на кожен тест — це саме те, чого ми хочемо і в проді, коли
    процес запускається з нуля.
    """
    from fastapi.testclient import TestClient

    from avelren import db
    from avelren.api import app

    db._pool = None
    with TestClient(app) as client:
        yield client


@pytest.fixture()
def device(conn) -> Installation:
    """Пристрій зі своєю парою (id, secret): без secret захищені ендпоінти
    відповідатимуть 401, тож тести без облікових даних просто б не працювали."""
    token = f"test-{random.randrange(10**12):012d}"
    secret = secrets.token_urlsafe(32)
    row = conn.execute(
        """
        INSERT INTO devices (fcm_token, secret_hash)
        VALUES (%s, crypt(%s, gen_salt('bf', 4)))
        RETURNING id
        """,
        (token, secret),
    ).fetchone()
    installation = Installation(device_id=str(row["id"]), device_secret=secret)
    try:
        yield installation
    finally:
        conn.execute("DELETE FROM devices WHERE id = %s", (installation.device_id,))
