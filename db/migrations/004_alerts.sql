-- Підписка анонімна: пристрій, а не людина. Персональних даних не збираємо,
-- тож і захищати нема чого.
CREATE TABLE IF NOT EXISTS devices (
    id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    fcm_token   text        UNIQUE,
    platform    text        NOT NULL DEFAULT 'android',
    created_at  timestamptz NOT NULL DEFAULT now(),
    last_seen   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id            bigserial   PRIMARY KEY,
    device_id     uuid        NOT NULL REFERENCES devices (id) ON DELETE CASCADE,
    checkpoint_id integer     NOT NULL REFERENCES checkpoints (id),
    threshold     integer     NOT NULL CHECK (threshold BETWEEN 50 AND 500),
    is_active     boolean     NOT NULL DEFAULT true,
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (device_id, checkpoint_id, threshold)
);

CREATE INDEX IF NOT EXISTS subscriptions_checkpoint_idx
    ON subscriptions (checkpoint_id) WHERE is_active;

-- Сповіщення живе, доки користувач не натисне «ОК». Стан тримає сервер, а не
-- телефон: інакше воно не переживало б перезавантаження чи вбивство застосунку.
CREATE TABLE IF NOT EXISTS alerts (
    id                  bigserial   PRIMARY KEY,
    subscription_id     bigint      NOT NULL REFERENCES subscriptions (id) ON DELETE CASCADE,
    checkpoint_id       integer     NOT NULL REFERENCES checkpoints (id),
    threshold           integer     NOT NULL,
    triggered_at        timestamptz NOT NULL DEFAULT now(),
    vehicles_at_trigger integer     NOT NULL,
    status              text        NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'acknowledged', 'expired')),
    last_sent_at        timestamptz,
    send_count          integer     NOT NULL DEFAULT 0,
    acknowledged_at     timestamptz,
    expired_at          timestamptz
);

-- По цьому індексу щохвилини бігає розсилач повторів.
CREATE INDEX IF NOT EXISTS alerts_pending_idx
    ON alerts (status, last_sent_at) WHERE status = 'pending';

-- Один незакритий алерт на підписку: доки не підтверджено, новий не потрібен.
CREATE UNIQUE INDEX IF NOT EXISTS alerts_one_pending_per_subscription
    ON alerts (subscription_id) WHERE status = 'pending';

-- Перезарядка після «ОК»: наступне спрацювання можливе лише коли черга впаде
-- нижче порога із запасом. Без запасу коливання 49<->51 будило б щохвилини.
CREATE TABLE IF NOT EXISTS subscription_state (
    subscription_id bigint      PRIMARY KEY REFERENCES subscriptions (id) ON DELETE CASCADE,
    is_armed        boolean     NOT NULL DEFAULT true,
    disarmed_at     timestamptz,
    rearmed_at      timestamptz
);
