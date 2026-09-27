-- PIN verification and attempt limits are enforced by the API while holding
-- admin_access FOR UPDATE. This narrow definer performs the privilege transfer.
CREATE FUNCTION public.activate_admin_after_pin(candidate uuid) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    access_row public.admin_access%ROWTYPE;
    candidate_row public.devices%ROWTYPE;
BEGIN
    SELECT * INTO access_row FROM public.admin_access WHERE singleton FOR UPDATE;
    IF NOT FOUND OR access_row.pin_hash IS NULL
       OR access_row.locked_until > clock_timestamp() THEN
        RAISE EXCEPTION 'Admin access denied' USING ERRCODE = '42501';
    END IF;

    SELECT * INTO candidate_row FROM public.devices WHERE id = candidate FOR UPDATE;
    IF NOT FOUND OR candidate_row.fcm_token IS NULL
       OR candidate_row.admin_blocked_until > clock_timestamp() THEN
        RAISE EXCEPTION 'Admin access denied' USING ERRCODE = '42501';
    END IF;

    -- The partial unique index allows at most one true row, so clear first.
    UPDATE public.devices SET is_admin = false WHERE is_admin AND id <> candidate;
    UPDATE public.admin_access
       SET approved_device_id = candidate, failures = 0, locked_until = NULL
     WHERE singleton;
    UPDATE public.devices SET is_admin = true WHERE id = candidate;
END;
$$;
ALTER FUNCTION public.activate_admin_after_pin(uuid) OWNER TO avelren_migrator;
REVOKE ALL ON FUNCTION public.activate_admin_after_pin(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.activate_admin_after_pin(uuid) TO avelren_api;
