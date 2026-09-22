-- Approval and lockout belong to the owner, not to a disposable installation.
CREATE TABLE admin_access (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    approved_device_id uuid REFERENCES devices(id) ON DELETE SET NULL,
    pin_hash text,
    failures integer NOT NULL DEFAULT 0 CHECK (failures BETWEEN 0 AND 3),
    locked_until timestamptz,
    CHECK ((failures = 3) = (locked_until IS NOT NULL))
);
INSERT INTO admin_access(singleton) VALUES (true);
REVOKE ALL ON TABLE admin_access FROM PUBLIC;
GRANT SELECT ON TABLE admin_access TO avelren_backup, avelren_api;
GRANT UPDATE(failures, locked_until) ON admin_access TO avelren_api;

-- A duplicate is a deployment blocker, not a reason to choose an owner silently.
CREATE UNIQUE INDEX devices_one_admin ON devices(is_admin) WHERE is_admin;

-- The API cannot approve an installation or update devices.is_admin directly.
CREATE FUNCTION activate_approved_admin(candidate uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    allowed uuid;
    blocked_until timestamptz;
BEGIN
    SELECT approved_device_id, locked_until INTO allowed, blocked_until
      FROM public.admin_access WHERE singleton FOR UPDATE;
    IF allowed IS NULL OR allowed <> candidate OR blocked_until > clock_timestamp() THEN
        RAISE EXCEPTION 'Admin access denied' USING ERRCODE = '42501';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.devices
                   WHERE id = candidate AND fcm_token IS NOT NULL) THEN
        RAISE EXCEPTION 'Admin token unavailable' USING ERRCODE = '42501';
    END IF;
    UPDATE public.devices SET is_admin = false WHERE is_admin AND id <> candidate;
    UPDATE public.devices SET is_admin = true WHERE id = candidate;
END;
$$;
REVOKE ALL ON FUNCTION activate_approved_admin(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION activate_approved_admin(uuid) TO avelren_api;
