-- Країни-сусіди. Прапор зберігаємо як emoji, а не посилання на чужу картинку:
-- клієнт не має ходити на echerha.gov.ua навіть по іконку (див. AGENTS.md).
CREATE TABLE IF NOT EXISTS countries (
    id          integer PRIMARY KEY,
    name        text        NOT NULL,
    flag_emoji  text,
    last_seen   timestamptz NOT NULL DEFAULT now()
);

-- Список КПП мусить лишатися актуальним сам: нові з'являються, старі зникають.
-- last_seen оновлюється щоциклу, тож зниклі відпадають зі списку без ручної правки.
ALTER TABLE checkpoints
    ADD COLUMN IF NOT EXISTS country_name text,
    ADD COLUMN IF NOT EXISTS flag_emoji   text;

CREATE INDEX IF NOT EXISTS checkpoints_last_seen_idx
    ON checkpoints (last_seen DESC);
