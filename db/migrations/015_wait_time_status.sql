-- Preserve existing measurements, including compressed legacy rows.
-- The default keeps old collectors' explicit five-column INSERT compatible.
ALTER TABLE observations
    ADD COLUMN wait_time_status text NOT NULL DEFAULT 'legacy_unknown';

ALTER TABLE observations
    ADD CONSTRAINT observations_wait_time_status_check CHECK (
        wait_time_status IN ('reported', 'missing', 'legacy_unknown')
        AND (wait_time_status <> 'missing' OR wait_time_seconds = 0)
        AND (wait_time_status <> 'reported' OR wait_time_seconds >= 0)
    );
