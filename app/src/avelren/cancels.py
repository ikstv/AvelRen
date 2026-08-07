"""Скасування вже показаних сповіщень (A-02).

Сервер — єдине джерело істини про активність alert. Коли alert покидає
`pending` не через локальний ACK (expire або каскадне видалення), телефон
треба повідомити, що ongoing-нотифікацію пора зняти. Два шари:

  1. cancel-push через FCM (швидкий шлях, тут);
  2. reconciliation на клієнті при foreground (гарантія збіжності, коли push
     загубився — окремо, через `active_alert_keys`).

Enqueue cancel'ів відбувається В ОДНІЙ ТРАНЗАКЦІЇ з переходом стану — це
роблять CTE в `alerts.expire_stale`/`eta.expire_passed` та delete-ендпоінти.
Тут — лише відправка з outbox, its lifecycle і canonical active-стан.
"""

import logging

from psycopg import AsyncConnection

log = logging.getLogger("avelren.cancels")

# Як довго пробуємо доставити cancel, перш ніж здатися. Age-based, а не
# лічильник спроб: notifier ходить раз на хвилину, тож 5 спроб = ~5 хв, і
# коротка перерва FCM залишила б ongoing-нотифікацію висіти надовго. Година
# ретраїв покриває типовий FCM-збій; після неї підстрахує reconciliation при
# наступному foreground (аудит A-02 / B3).
ABANDON_AFTER = "1 hour"


async def fetch_open(conn: AsyncConnection) -> list[dict]:
    """Ще не закриті cancel'и разом із поточним токеном пристрою."""
    return await (
        await conn.execute(
            """
            SELECT nc.id, nc.kind, nc.alert_id, nc.attempt_count,
                   nc.device_id, d.fcm_token
            FROM notification_cancels nc
            JOIN devices d ON d.id = nc.device_id
            WHERE nc.accepted_at IS NULL AND nc.abandoned_at IS NULL
            ORDER BY nc.created_at
            """
        )
    ).fetchall()


async def mark_accepted(conn: AsyncConnection, cancel_id: int) -> None:
    await conn.execute(
        "UPDATE notification_cancels SET accepted_at = now() WHERE id = %s",
        (cancel_id,),
    )


async def record_attempt(conn: AsyncConnection, cancel_id: int) -> None:
    """Фіксує невдалу спробу; здаємось лише коли запис старший за ABANDON_AFTER.

    attempt_count лишається для діагностики, але рішення про abandon — за віком
    created_at, а не за кількістю спроб (див. ABANDON_AFTER).
    """
    await conn.execute(
        f"""
        UPDATE notification_cancels
        SET attempt_count = attempt_count + 1,
            last_attempt_at = now(),
            abandoned_at = CASE
                WHEN created_at < now() - INTERVAL '{ABANDON_AFTER}' THEN now()
                ELSE NULL
            END
        WHERE id = %s
        """,
        (cancel_id,),
    )


async def mark_abandoned(conn: AsyncConnection, cancel_id: int) -> None:
    """Здаємось одразу (мертвий токен: пристрою вже нема кому показувати)."""
    await conn.execute(
        "UPDATE notification_cancels SET abandoned_at = now(), last_attempt_at = now() "
        "WHERE id = %s",
        (cancel_id,),
    )


async def cleanup_closed(conn: AsyncConnection) -> None:
    """Прибирає закриті записи, старші за добу: історія тут не потрібна."""
    await conn.execute(
        """
        DELETE FROM notification_cancels
        WHERE (accepted_at IS NOT NULL OR abandoned_at IS NOT NULL)
          AND created_at < now() - INTERVAL '1 day'
        """
    )


async def active_alert_keys(conn: AsyncConnection, device_id: str) -> dict[str, list[int]]:
    """Canonical перелік активних (pending) alert'ів пристрою — для
    reconciliation. Свідомо БЕЗ фільтра send_count: істина — статус, а не
    історія успішного запису лічильника. Порожні списки — усе закрито.
    """
    threshold = await (
        await conn.execute(
            """
            SELECT a.id
            FROM alerts a
            JOIN subscriptions s ON s.id = a.subscription_id
            WHERE s.device_id = %s AND a.status = 'pending'
            ORDER BY a.id
            """,
            (device_id,),
        )
    ).fetchall()
    eta = await (
        await conn.execute(
            """
            SELECT a.id
            FROM eta_alerts a
            JOIN eta_targets t ON t.id = a.target_id
            WHERE t.device_id = %s AND a.status = 'pending'
            ORDER BY a.id
            """,
            (device_id,),
        )
    ).fetchall()
    return {
        "threshold": [r["id"] for r in threshold],
        "eta": [r["id"] for r in eta],
    }
