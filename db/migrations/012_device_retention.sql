-- Fixed 90-day retention; callers cannot choose a cutoff or a device to delete.
-- No new tables or sequences: existing backup grants remain unchanged.
CREATE FUNCTION prune_inactive_devices(apply_changes boolean DEFAULT false)
RETURNS TABLE(candidates bigint, deleted bigint)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $$
DECLARE
    cutoff timestamptz := transaction_timestamp() - INTERVAL '90 days';
BEGIN
    SELECT count(*) INTO candidates FROM public.devices WHERE last_seen < cutoff;
    deleted := 0;
    IF apply_changes THEN
        -- Same lock order as admin approval/activation. An expired admin is
        -- deleted too; FK clears approval, never the PIN or lockout counters.
        PERFORM 1 FROM public.admin_access WHERE singleton FOR UPDATE;
        WITH expired AS (
            SELECT id FROM public.devices
            WHERE last_seen < cutoff ORDER BY last_seen, id
            LIMIT 500 FOR UPDATE SKIP LOCKED
        ), removed AS (
            DELETE FROM public.devices d USING expired e
            WHERE d.id = e.id AND d.last_seen < cutoff RETURNING d.id
        ) SELECT count(*) INTO deleted FROM removed;
    END IF;
    RETURN NEXT;
END;
$$;
ALTER FUNCTION prune_inactive_devices(boolean) OWNER TO avelren_migrator;
REVOKE ALL ON FUNCTION prune_inactive_devices(boolean) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION prune_inactive_devices(boolean) TO avelren_notifier;
