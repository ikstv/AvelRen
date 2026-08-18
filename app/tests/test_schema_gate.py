"""Стартовий гейт схеми (issue #88).

Гейт, який ніколи не бачили червоним, — не гейт. Тому більшість тестів тут
доводять ВІДМОВУ, а не прохід: підсовують занизьку версію, порожній журнал і
некоректний формат, і вимагають винятку. Зелений прогін проти реальної
тестової БД тут лише один — він доводить, що дріт справді підключений
(і що грант із міграції 010 на місці).
"""

import asyncio
import os

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from avelren.schema_gate import (
    SchemaTooOldError,
    _version_ordinal,
    assert_schema_at_least,
    check_recorded_version,
    highest_recorded,
)

DSN = os.environ["DATABASE_URL"]

# Пін поточної вимоги. Значення ПОХІДНЕ (виводиться з version-анотованого
# контракту schema_verify), тож цей тест не дублює логіку — він робить її зміну
# видимою в рев'ю. Міграція, яка вводить новий об'єкт у контракт, зобов'язана
# змінити цей рядок разом із собою; міграція без нових об'єктів (як 010, самі
# гранти) — не зобов'язана й не сміє.
EXPECTED_REQUIREMENT = "009_observability"


def _run(coro):
    return asyncio.run(coro)


# --- вимога виводиться, а не вигадується ------------------------------------


def test_requirement_matches_pinned_value():
    from avelren.schema_gate import required_schema_version

    assert required_schema_version() == EXPECTED_REQUIREMENT


def test_requirement_ignores_grant_only_migrations():
    """010 не вводить жодного об'єкта контракту, тож вимогу не піднімає.

    Інакше сервіс відмовлявся б стартувати через незастосований ACL-шар —
    саме той стан, у якому прод перебуває між 3B.2 і 3D."""
    from avelren.schema_gate import required_schema_version

    assert _version_ordinal(required_schema_version()) < _version_ordinal("010_x")


# --- порядок версій: пастка 009 -> 010 --------------------------------------


def test_ordinal_is_numeric_not_lexicographic():
    assert _version_ordinal("010_least_privilege") > _version_ordinal("009_observability")
    assert _version_ordinal("100_future") > _version_ordinal("099_past")


def test_ordinal_rejects_malformed_version():
    with pytest.raises(ValueError):
        _version_ordinal("draft_something")


# --- найвища версія береться числово, а не текстово -------------------------


def test_highest_recorded_is_numeric_not_textual():
    """Саме тут ховалася б тиха помилка, якби покладатись на SQL max(version)."""
    assert highest_recorded(["009_observability", "010_least_privilege"]) == "010_least_privilege"


def test_highest_recorded_survives_mixed_padding():
    """Текстовий max повернув би тут `009_x` — тобто старішу за фактичну."""
    assert highest_recorded(["009_x", "0010_y"]) == "0010_y"


def test_highest_recorded_on_empty_ledger_is_none():
    assert highest_recorded([]) is None


# --- ФАЛЬСИФІКАЦІЯ: гейт мусить відмовляти ----------------------------------


def test_older_schema_is_refused():
    with pytest.raises(SchemaTooOldError) as excinfo:
        check_recorded_version("008_notification_cancels")
    assert "008_notification_cancels" in str(excinfo.value)
    assert EXPECTED_REQUIREMENT in str(excinfo.value)


def test_empty_ledger_is_refused_not_treated_as_fresh():
    """Порожній журнал — це схема без жодної міграції, а не «нова база, ок»."""
    with pytest.raises(SchemaTooOldError):
        check_recorded_version(None)


def test_exact_requirement_passes():
    check_recorded_version(EXPECTED_REQUIREMENT)


def test_newer_schema_passes():
    check_recorded_version("010_postgresql_least_privilege")


# --- дріт справді підключений ------------------------------------------------


def test_gate_passes_against_real_database():
    """Наскрізно: справжній пул, справжній SELECT, справжній грант.

    Падіння з 42501 тут означало б, що роль не має SELECT на schema_migrations —
    тобто що передумова з міграції 010 не застосована."""

    async def run():
        pool = AsyncConnectionPool(
            DSN, min_size=1, max_size=1, open=False, kwargs={"row_factory": dict_row}
        )
        await pool.open(wait=True, timeout=30)
        try:
            await assert_schema_at_least(pool)
        finally:
            await pool.close()

    _run(run())


def test_real_ledger_is_populated_and_older_pin_would_refuse():
    """Дві речі поруч: тестова БД справді має застосовані міграції, і той самий
    гейт на штучно заниженій версії відмовляє. Назва навмисно описує рівно те,
    що перевіряється — тест, чия назва ширша за поведінку, зеленіє не з тієї
    причини."""

    async def run():
        async with await psycopg.AsyncConnection.connect(DSN, autocommit=True) as conn:
            conn.row_factory = dict_row
            row = await (
                await conn.execute("SELECT max(version) AS version FROM schema_migrations")
            ).fetchone()
            return row["version"]

    recorded = _run(run())
    assert recorded is not None, "тестова БД має мати застосовані міграції"
    # А тепер та сама перевірка на штучно «зіпсованому» результаті.
    with pytest.raises(SchemaTooOldError):
        check_recorded_version("001_init")
