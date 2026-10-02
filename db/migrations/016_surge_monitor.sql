-- Експериментальний моніторинг: окремі епізоди, ACK та стійкі FCM-спроби.
-- Роль попередньо створюється адміністратором через surge-bootstrap.sql.
ALTER TABLE devices ADD COLUMN notification_capabilities text[] NOT NULL DEFAULT '{}';

CREATE TABLE surge_subscriptions (
    id bigserial PRIMARY KEY,
    device_id uuid NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    checkpoint_id integer NOT NULL REFERENCES checkpoints(id),
    forecast_enabled boolean NOT NULL DEFAULT true,
    fact_enabled boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(device_id,checkpoint_id)
);
CREATE TABLE surge_predictions (
    id bigserial PRIMARY KEY,
    checkpoint_id integer NOT NULL REFERENCES checkpoints(id),
    issued_at timestamptz NOT NULL,
    window_start timestamptz NOT NULL,
    window_end timestamptz NOT NULL,
    model_version text NOT NULL,
    score double precision,
    reason text,
    CHECK(window_start > issued_at AND window_end > window_start),
    CHECK(score IS NULL OR (score >= 0 AND score <= 1)),
    CHECK((score IS NULL AND reason IS NOT NULL) OR (score IS NOT NULL AND reason IS NULL)),
    UNIQUE(checkpoint_id,issued_at,model_version)
);
CREATE TABLE surge_events (
    id bigserial PRIMARY KEY,
    checkpoint_id integer NOT NULL REFERENCES checkpoints(id),
    kind text NOT NULL CHECK(kind IN ('surge_forecast','surge_started')),
    started_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    closed_at timestamptz,
    close_reason text,
    prediction_id bigint REFERENCES surge_predictions(id),
    growth integer,
    CHECK(updated_at >= started_at AND expires_at >= started_at),
    CHECK((closed_at IS NULL AND close_reason IS NULL) OR (closed_at IS NOT NULL AND close_reason IS NOT NULL))
);
CREATE UNIQUE INDEX surge_events_one_active ON surge_events(checkpoint_id,kind) WHERE closed_at IS NULL;
CREATE TABLE surge_alerts (
    id bigserial PRIMARY KEY,
    event_id bigint NOT NULL REFERENCES surge_events(id) ON DELETE CASCADE,
    device_id uuid NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','acknowledged','expired')),
    created_at timestamptz NOT NULL DEFAULT now(),
    acknowledged_at timestamptz,
    next_attempt_at timestamptz NOT NULL,
    UNIQUE(event_id,device_id)
);
CREATE INDEX surge_alerts_pending ON surge_alerts(next_attempt_at) WHERE status='pending';
CREATE TABLE surge_delivery_attempts (
    id bigserial PRIMARY KEY,
    attempt_id uuid NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    alert_id bigint NOT NULL REFERENCES surge_alerts(id) ON DELETE CASCADE,
    ordinal integer NOT NULL CHECK(ordinal > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    last_attempt_at timestamptz,
    accepted_at timestamptz,
    abandoned_at timestamptz,
    attempt_count integer NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
    CHECK(accepted_at IS NULL OR abandoned_at IS NULL),
    UNIQUE(alert_id,ordinal)
);
CREATE TABLE surge_checkpoint_state (
    checkpoint_id integer PRIMARY KEY REFERENCES checkpoints(id),
    last_observation_at timestamptz,
    last_forecast_hour timestamptz,
    forecast_armed boolean NOT NULL DEFAULT true,
    last_growth_at timestamptz
);
ALTER TABLE notification_cancels DROP CONSTRAINT notification_cancels_kind_check;
ALTER TABLE notification_cancels ADD CONSTRAINT notification_cancels_kind_check
    CHECK(kind IN ('threshold','eta','surge_forecast','surge_started'));

GRANT SELECT ON surge_subscriptions,surge_predictions,surge_events,surge_alerts,
    surge_delivery_attempts,surge_checkpoint_state TO avelren_backup;
GRANT SELECT ON SEQUENCE surge_subscriptions_id_seq,surge_predictions_id_seq,
    surge_events_id_seq,surge_alerts_id_seq,surge_delivery_attempts_id_seq TO avelren_backup;
GRANT SELECT ON observations,checkpoints,schema_migrations,surge_subscriptions TO avelren_surge;
GRANT SELECT(id,notification_capabilities) ON devices TO avelren_surge;
GRANT SELECT,INSERT,UPDATE ON surge_predictions,surge_events,surge_alerts,
    surge_checkpoint_state TO avelren_surge;
GRANT INSERT ON notification_cancels TO avelren_surge;
GRANT USAGE ON SEQUENCE surge_predictions_id_seq,surge_events_id_seq,
    surge_alerts_id_seq,notification_cancels_id_seq TO avelren_surge;
GRANT SELECT ON surge_predictions,surge_events TO avelren_api;
GRANT SELECT,INSERT,UPDATE,DELETE ON surge_subscriptions TO avelren_api;
GRANT SELECT,INSERT,UPDATE ON surge_alerts TO avelren_api;
GRANT USAGE ON SEQUENCE surge_subscriptions_id_seq,surge_alerts_id_seq TO avelren_api;
GRANT INSERT(notification_capabilities), UPDATE(notification_capabilities) ON devices TO avelren_api;
GRANT SELECT ON surge_events TO avelren_notifier;
GRANT SELECT,UPDATE ON surge_alerts TO avelren_notifier;
GRANT SELECT,INSERT,UPDATE ON surge_delivery_attempts TO avelren_notifier;
GRANT USAGE ON SEQUENCE surge_delivery_attempts_id_seq TO avelren_notifier;
