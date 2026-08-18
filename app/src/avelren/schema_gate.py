"""Fail-closed перевірка версії схеми при старті сервісу (issue #88).

ЧОМУ ЦЕ ІСНУЄ. Досі узгодженість схеми з кодом гарантував лише сервіс
`migrate`, який виконується перед кожним стартом. Це працює, але тримається на
СПОСОБІ ЗАПУСКУ: досить підняти сервіс іншою командою — і жоден процес більше
не звіряє, на якій схемі він працює. Після Gate 11 3B.2 ця крихкість стала
відчутною: `avelren_migrator` отримав повні права, тож випадковий
`docker compose up -d` тепер не падає гучно, а тихо застосовує й штампує
наступну міграцію поза послідовністю.

Перевірка тут переносить fail-closed УСЕРЕДИНУ застосунку — туди, де його не
обійти способом запуску. Саме це відкриває шлях повернути `migrate` за
профіль (див. коментар до migrate у docker-compose.yml).

ЩО САМЕ ПОРІВНЮЄТЬСЯ. Не «остання міграція в каталозі» — рантайм-контейнери
каталогу міграцій не бачать. Порівнюється найвища версія, ЗАПИСАНА в
`schema_migrations`, з найвищою версією, яку вимагає фізичний контракт коду.

ЧОМУ ВИМОГА ПОХІДНА, А НЕ КОНСТАНТА. Константа, виставлена руками, протухає
мовчки: хтось додає міграцію, забуває підняти число, і гейт пропускає схему,
якої коду бракує. Тому вимога виводиться з version-анотованого контракту
`schema_verify`, який і так мусить оновлюватися разом зі схемою. Забути можна
одне місце замість двох.

Наслідок, важливий для розуміння: міграції, що НЕ вводять нових об'єктів
(наприклад `010_postgresql_least_privilege` — самі лише гранти), вимогу не
піднімають. Це навмисно: код на них структурно не спирається, і сервіс не має
відмовлятися стартувати через незастосований ACL-шар.
"""

import logging

from psycopg.rows import tuple_row
from psycopg_pool import AsyncConnectionPool

from . import schema_verify

log = logging.getLogger("avelren.schema_gate")


class SchemaTooOldError(RuntimeError):
    """Схема БД старша за ту, якої вимагає код цього сервісу."""


def _version_ordinal(version: str) -> int:
    """`009_observability` -> 9. Лексикографічне порівняння тут не годиться:
    воно розсиплеться на переході 009 -> 010 -> 100, а прикидатиметься робочим."""
    prefix = version.split("_", 1)[0]
    if not prefix.isdigit():
        raise ValueError(f"версія міграції без числового префікса: {version!r}")
    return int(prefix)


def required_schema_version() -> str:
    """Найвища версія, яка вводить об'єкт, потрібний фізичному контракту коду."""
    versions = {
        since
        for group in (
            schema_verify._TABLES_V,
            schema_verify._COLUMNS_V,
            schema_verify._UNIQUE_PARTIAL_INDEXES_V,
            schema_verify._INDEXES_V,
            schema_verify._CONSTRAINTS_V,
            schema_verify._HYPERTABLES_V,
            schema_verify._CONTINUOUS_AGGREGATES_V,
        )
        for since in (entry[0] for entry in group)
        if since is not None
    }
    if not versions:
        raise RuntimeError("контракт схеми порожній — вимогу неможливо вивести")
    return max(versions, key=_version_ordinal)


def highest_recorded(versions: list[str]) -> str | None:
    """Найвища версія за ЧИСЛОВИМ порядком, не за текстовим.

    SQL `max(version)` тут не годиться: він текстовий. Для акуратно
    нуль-доповнених 001…010 він випадково збігається з числовим — і саме тому
    небезпечний: виглядає робочим і зламається тихо. Достатньо однієї версії з
    іншим падінгом (`0010_x` поруч із `009_x`), щоб текстовий max повернув
    старішу, а гейт відмовив на цілком свіжій схемі."""
    if not versions:
        return None
    return max(versions, key=_version_ordinal)


def check_recorded_version(recorded: str | None) -> None:
    """Чиста частина гейта: підняти виняток, якщо записана версія замала.

    `recorded is None` означає порожній журнал міграцій — це НЕ «нова база, все
    гаразд», а схема без жодної застосованої міграції. Fail-closed."""
    required = required_schema_version()
    if recorded is None:
        raise SchemaTooOldError(
            f"журнал міграцій порожній; код вимагає щонайменше {required}"
        )
    if _version_ordinal(recorded) < _version_ordinal(required):
        raise SchemaTooOldError(
            f"схема БД на {recorded}; код вимагає щонайменше {required}"
        )


async def assert_schema_at_least(pool: AsyncConnectionPool) -> None:
    """Викликається одразу після відкриття пулу, до будь-якої корисної роботи.

    Будь-яка помилка запиту (немає таблиці, 42501 через відсутній грант) — теж
    відмова: ми не можемо довести узгодженість, отже не працюємо. Мовчазний
    прохід тут був би гіршим за падіння."""
    # tuple_row задається явно: інакше форма рядка залежала б від row_factory
    # пулу, і гейт мовчки зламався б у процесі, налаштованому інакше.
    async with pool.connection() as conn:
        cursor = conn.cursor(row_factory=tuple_row)
        await cursor.execute("SELECT version FROM schema_migrations")
        rows = await cursor.fetchall()
    recorded = highest_recorded([row[0] for row in rows])
    check_recorded_version(recorded)
    log.info("схема узгоджена зі стартовою вимогою: %s", recorded)
