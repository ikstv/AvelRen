CREATE EXTENSION IF NOT EXISTS timescaledb;

-- Довідник черг. Оновлюється upsert-ом на кожному циклі: пункти з'являються,
-- зникають і змінюють назви, довідник має переживати це без ручного втручання.
CREATE TABLE IF NOT EXISTS checkpoints (
    id                 integer PRIMARY KEY,
    title              text        NOT NULL,
    country_id         integer,
    for_vehicle_type   smallint    NOT NULL,
    queue_flow         smallint,
    cancel_after       integer,
    lat                double precision,
    lng                double precision,
    first_seen         timestamptz NOT NULL DEFAULT now(),
    last_seen          timestamptz NOT NULL DEFAULT now()
);

-- Часовий ряд спостережень. Пишемо кожне опитування без дедуплікації:
-- прогалину потім не відновиш, бо джерело історії не зберігає.
CREATE TABLE IF NOT EXISTS observations (
    time               timestamptz NOT NULL,
    checkpoint_id      integer     NOT NULL REFERENCES checkpoints (id),
    wait_time_seconds  integer     NOT NULL,
    vehicles_in_queue  integer     NOT NULL,
    is_paused          boolean     NOT NULL,
    PRIMARY KEY (checkpoint_id, time)
);

SELECT create_hypertable('observations', 'time', if_not_exists => TRUE);

CREATE INDEX IF NOT EXISTS observations_time_idx
    ON observations (time DESC);

-- Журнал циклів, включно з невдалими. Без нього діагностика «чому за вівторок
-- немає даних» перетворюється на гадання.
CREATE TABLE IF NOT EXISTS collector_runs (
    time            timestamptz PRIMARY KEY DEFAULT now(),
    http_status     integer,
    duration_ms     integer,
    body_sha256     text,
    rows_written    integer     NOT NULL DEFAULT 0,
    error           text
);

CREATE INDEX IF NOT EXISTS collector_runs_time_idx
    ON collector_runs (time DESC);

-- Стиснення старших даних. 20 млн рядків на рік стискаються в рази.
ALTER TABLE observations SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'checkpoint_id',
    timescaledb.compress_orderby   = 'time DESC'
);

SELECT add_compression_policy('observations', INTERVAL '7 days', if_not_exists => TRUE);

-- Погодинні агрегати для графіків: рахувати їх на льоту по мільйонах рядків дорого.
CREATE MATERIALIZED VIEW IF NOT EXISTS observations_hourly
WITH (timescaledb.continuous) AS
SELECT
    time_bucket(INTERVAL '1 hour', time) AS bucket,
    checkpoint_id,
    avg(wait_time_seconds)::integer  AS avg_wait_seconds,
    max(wait_time_seconds)           AS max_wait_seconds,
    avg(vehicles_in_queue)::integer  AS avg_vehicles,
    max(vehicles_in_queue)           AS max_vehicles,
    count(*)                         AS samples
FROM observations
GROUP BY bucket, checkpoint_id
WITH NO DATA;

SELECT add_continuous_aggregate_policy('observations_hourly',
    start_offset      => INTERVAL '3 days',
    end_offset        => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists     => TRUE);
