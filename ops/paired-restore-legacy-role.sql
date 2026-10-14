-- Лише disposable paired rehearsal: ім'я власника Timescale job у старому dump.
-- Це не відновлення production-повноважень і не доказ виконання job.
DO $$
BEGIN
    IF current_setting('avelren.paired_rehearsal', true) IS DISTINCT FROM '1' THEN
        RAISE EXCEPTION 'legacy_role_rehearsal_required';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'avelren') THEN
        CREATE ROLE avelren NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOREPLICATION NOBYPASSRLS;
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'avelren'
        AND (rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole
             OR rolreplication OR rolbypassrls)
    ) OR EXISTS (
        SELECT 1 FROM pg_auth_members
        WHERE member = 'avelren'::regrole OR roleid = 'avelren'::regrole
    ) THEN
        RAISE EXCEPTION 'legacy_role_attributes_refused';
    END IF;
END $$;
