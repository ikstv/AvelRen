-- Preserve existing measurements, including compressed legacy rows.
-- Do not add a historical DEFAULT: its missing-value metadata does not survive
-- the compressed-chunk logical restore contract. NULL means legacy_unknown.
ALTER TABLE observations
    ADD COLUMN wait_time_status text;

-- Only future old-collector INSERTs receive this default, without backfill.
ALTER TABLE observations
    ALTER COLUMN wait_time_status SET DEFAULT 'legacy_unknown';

ALTER TABLE observations
    ADD CONSTRAINT observations_wait_time_status_check CHECK (
        wait_time_status IS NULL OR (
            wait_time_status IN ('reported', 'missing', 'legacy_unknown')
            AND (wait_time_status <> 'missing' OR wait_time_seconds = 0)
            AND (wait_time_status <> 'reported' OR wait_time_seconds >= 0)
        )
    );
