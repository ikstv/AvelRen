-- /checkpoints сортує по (country_name, title) на кожному відкритті списку.
CREATE INDEX IF NOT EXISTS checkpoints_country_title_idx
    ON checkpoints (country_name, title);
