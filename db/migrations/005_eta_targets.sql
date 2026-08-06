-- Функція №2: «хочу в'їхати о 22:15».
--
-- Зворотна задача до першої функції. Там стежимо за кількістю авто, тут — за
-- орієнтовним часом в'їзду: момент заміру + wait_time. Коли він потрапляє у
-- вікно навколо цілі, користувачу час реєструватися в єЧерзі.
--
-- Окремої таблиці спостережень не треба: wait_time_seconds уже в observations
-- з першого дня збору.
CREATE TABLE IF NOT EXISTS eta_targets (
    id             bigserial   PRIMARY KEY,
    device_id      uuid        NOT NULL REFERENCES devices (id) ON DELETE CASCADE,
    checkpoint_id  integer     NOT NULL REFERENCES checkpoints (id),
    -- Цільовий момент в'їзду. Саме timestamptz, а не «час доби»: черги тут
    -- тривають днями, і 22:15 без дати не має сенсу.
    target_at      timestamptz NOT NULL,
    tolerance_seconds integer  NOT NULL DEFAULT 900 CHECK (tolerance_seconds > 0),
    is_active      boolean     NOT NULL DEFAULT true,
    created_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (device_id, checkpoint_id, target_at)
);

CREATE INDEX IF NOT EXISTS eta_targets_active_idx
    ON eta_targets (checkpoint_id) WHERE is_active;

-- Спрацювання. Як і в функції №1, стан тримає сервер: сповіщення повторюється,
-- доки користувач не натисне «ОК».
CREATE TABLE IF NOT EXISTS eta_alerts (
    id              bigserial   PRIMARY KEY,
    target_id       bigint      NOT NULL REFERENCES eta_targets (id) ON DELETE CASCADE,
    checkpoint_id   integer     NOT NULL REFERENCES checkpoints (id),
    triggered_at    timestamptz NOT NULL DEFAULT now(),
    -- Що саме побачив сервер у момент спрацювання: для довіри до сповіщення
    -- і для розбору, якщо користувач скаже «прийшло, а час був інший».
    eta_at_trigger  timestamptz NOT NULL,
    wait_seconds_at_trigger integer NOT NULL,
    status          text        NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'acknowledged', 'expired')),
    last_sent_at    timestamptz,
    send_count      integer     NOT NULL DEFAULT 0,
    acknowledged_at timestamptz,
    expired_at      timestamptz
);

CREATE INDEX IF NOT EXISTS eta_alerts_pending_idx
    ON eta_alerts (status, last_sent_at) WHERE status = 'pending';

-- Один незакритий алерт на ціль: вікно триває багато хвилин, і щохвилинне
-- сповіщення про ту саму подію перетворило б функцію на спам.
CREATE UNIQUE INDEX IF NOT EXISTS eta_alerts_one_pending_per_target
    ON eta_alerts (target_id) WHERE status = 'pending';
