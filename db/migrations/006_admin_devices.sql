-- Моніторинг шле тривоги тим самим каналом, що й звичайні сповіщення: FCM на
-- телефон адміністратора. Окрема система сповіщень (пошта, Telegram) означала б
-- ще один сервіс, ще один секрет і ще одну точку відмови.
ALTER TABLE devices
    ADD COLUMN IF NOT EXISTS is_admin boolean NOT NULL DEFAULT false;

-- Журнал тривог. Потрібен не для історії, а щоб не слати те саме щоп'ять
-- хвилин: сервер лежить годину — це одна тривога, а не дванадцять.
CREATE TABLE IF NOT EXISTS health_alerts (
    id            bigserial   PRIMARY KEY,
    kind          text        NOT NULL,
    detail        text,
    first_seen    timestamptz NOT NULL DEFAULT now(),
    last_sent_at  timestamptz,
    send_count    integer     NOT NULL DEFAULT 0,
    resolved_at   timestamptz
);

-- Одна незакрита тривога на тип проблеми.
CREATE UNIQUE INDEX IF NOT EXISTS health_alerts_one_open_per_kind
    ON health_alerts (kind) WHERE resolved_at IS NULL;
