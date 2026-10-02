\set ON_ERROR_STOP on
-- Bootstrap не надає login та не містить пароль. Окреме production GO
-- потрібне для LOGIN/password, CONNECT та запуску worker.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='avelren_surge') THEN
        CREATE ROLE avelren_surge NOLOGIN NOINHERIT NOSUPERUSER NOCREATEDB
            NOCREATEROLE NOREPLICATION NOBYPASSRLS;
    END IF;
END $$;
