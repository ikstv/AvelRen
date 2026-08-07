-- Durable outbox для скасування вже показаних сповіщень (аудит A-02).
--
-- Проблема: сервер може закрити alert (expire, коли черга впала нижче порога
-- або ETA-момент минув; або каскадне видалення при видаленні підписки/цілі),
-- але Android-сповіщення має setOngoing(true) і саме не зникає. Сервер —
-- єдине джерело істини про активність alert; телефон лише відображає цей стан.
--
-- Чому окрема таблиця, а не колонка на alerts: при каскадному DELETE рядок
-- alert зникає, тож «треба скасувати цю нотифікацію» колонкою на ньому не
-- відстежити. Запис тут переживає видалення батька — він прив'язаний до
-- device (який лишається), а не до alert.
--
-- Свідомо БЕЗ прив'язки до send_count: notifier робить fcm.send() ДО
-- _mark_sent(), тож існує crash-window, коли телефон показав нотифікацію, а
-- send_count у БД ще 0. Тому cancel enqueue-иться на будь-якому переході
-- pending → expired/deleted. Скасувати неіснуючу нотифікацію — безпечний
-- no-op на клієнті.

CREATE TABLE IF NOT EXISTS notification_cancels (
    id              bigserial   PRIMARY KEY,
    kind            text        NOT NULL CHECK (kind IN ('threshold', 'eta')),
    alert_id        bigint      NOT NULL CHECK (alert_id > 0),
    device_id       uuid        NOT NULL REFERENCES devices (id) ON DELETE CASCADE,
    created_at      timestamptz NOT NULL DEFAULT now(),
    attempt_count   integer     NOT NULL DEFAULT 0,
    last_attempt_at timestamptz,
    -- Рівно одне з двох закриває запис:
    --   accepted_at  — FCM прийняв cancel (HTTP 200). Це НЕ доказ, що телефон
    --                  показав/сховав — лише що Google прийняв. Точнішого
    --                  сигналу немає, і reconciliation усе одно підстрахує.
    --   abandoned_at — вичерпали спроби або токен мертвий; віддаємо це
    --                  reconciliation при наступному foreground.
    accepted_at     timestamptz,
    abandoned_at    timestamptz,
    -- Один відкритий cancel на (kind, alert_id). threshold:5 і eta:5 —
    -- НЕЗАЛЕЖНІ послідовності БД, тож це різні рядки; композитний ключ їх
    -- розводить.
    UNIQUE (kind, alert_id)
);

-- По цьому індексу notifier щоциклу вибирає ще не закриті cancel'и.
CREATE INDEX IF NOT EXISTS notification_cancels_open_idx
    ON notification_cancels (created_at)
    WHERE accepted_at IS NULL AND abandoned_at IS NULL;
