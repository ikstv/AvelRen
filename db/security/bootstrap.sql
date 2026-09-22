\set ON_ERROR_STOP on

-- Passwords come from the process environment and are rendered as SQL literals by
-- the server. They never appear in a psql command-line argument.
\getenv avelren_admin_password AVELREN_ADMIN_PASSWORD
\getenv avelren_migrator_password AVELREN_MIGRATOR_PASSWORD
\getenv avelren_backup_password AVELREN_BACKUP_PASSWORD
\getenv avelren_collector_password AVELREN_COLLECTOR_PASSWORD
\getenv avelren_notifier_password AVELREN_NOTIFIER_PASSWORD
\getenv avelren_watchdog_password AVELREN_WATCHDOG_PASSWORD
\getenv avelren_api_password AVELREN_API_PASSWORD

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'avelren_admin') THEN
        CREATE ROLE avelren_admin LOGIN SUPERUSER;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'avelren_migrator') THEN
        CREATE ROLE avelren_migrator LOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'avelren_backup') THEN
        CREATE ROLE avelren_backup LOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'avelren_collector') THEN
        CREATE ROLE avelren_collector LOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'avelren_notifier') THEN
        CREATE ROLE avelren_notifier LOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'avelren_watchdog') THEN
        CREATE ROLE avelren_watchdog LOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'avelren_api') THEN
        CREATE ROLE avelren_api LOGIN;
    END IF;
END
$$;

ALTER ROLE avelren_admin LOGIN SUPERUSER;
ALTER ROLE avelren_migrator LOGIN NOINHERIT NOBYPASSRLS;
ALTER ROLE avelren_backup LOGIN NOINHERIT NOBYPASSRLS;
ALTER ROLE avelren_collector LOGIN NOINHERIT NOBYPASSRLS;
ALTER ROLE avelren_notifier LOGIN NOINHERIT NOBYPASSRLS;
ALTER ROLE avelren_watchdog LOGIN NOINHERIT NOBYPASSRLS;
ALTER ROLE avelren_api LOGIN NOINHERIT NOBYPASSRLS;

ALTER ROLE avelren_migrator NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
ALTER ROLE avelren_backup NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
ALTER ROLE avelren_collector NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
ALTER ROLE avelren_notifier NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
ALTER ROLE avelren_watchdog NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
ALTER ROLE avelren_api NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;

REVOKE avelren_admin FROM avelren_migrator, avelren_backup, avelren_collector,
    avelren_notifier, avelren_watchdog, avelren_api;
REVOKE avelren_migrator FROM avelren_backup, avelren_collector,
    avelren_notifier, avelren_watchdog, avelren_api;

SELECT format('ALTER ROLE avelren_admin PASSWORD %L', :'avelren_admin_password') \gexec
SELECT format('ALTER ROLE avelren_migrator PASSWORD %L', :'avelren_migrator_password') \gexec
SELECT format('ALTER ROLE avelren_backup PASSWORD %L', :'avelren_backup_password') \gexec
SELECT format('ALTER ROLE avelren_collector PASSWORD %L', :'avelren_collector_password') \gexec
SELECT format('ALTER ROLE avelren_notifier PASSWORD %L', :'avelren_notifier_password') \gexec
SELECT format('ALTER ROLE avelren_watchdog PASSWORD %L', :'avelren_watchdog_password') \gexec
SELECT format('ALTER ROLE avelren_api PASSWORD %L', :'avelren_api_password') \gexec
