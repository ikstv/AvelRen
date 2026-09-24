-- A foreign installation must not be able to lock the owner's Admin access.
-- The deadline belongs to that installation and survives process restarts.
ALTER TABLE devices ADD COLUMN admin_blocked_until timestamptz;
GRANT SELECT (admin_blocked_until), UPDATE (admin_blocked_until)
    ON devices TO avelren_api;
-- Existing backup SELECT on devices also covers this new column.
