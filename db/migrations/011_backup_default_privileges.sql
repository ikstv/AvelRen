-- Backup must be able to read every FUTURE migrator-owned object, not only the
-- tables that existed when 010 was written.
--
-- Why this is not cosmetic: 010 grants SELECT to avelren_backup by an explicit
-- table list, and its ALTER DEFAULT PRIVILEGES block only REVOKEs from PUBLIC --
-- it grants nothing.  So the first migration that adds a table makes
-- `pg_dump -U avelren_backup` (deploy/backup.sh) fail with SQLSTATE 42501, and
-- nothing in CI notices: the backup role had only negative tests plus a
-- frozen-ACL snapshot of the tables that already existed.  The failure would
-- surface in production ~36 hours later, as BACKUP_STALE_HOURS in the watchdog --
-- that is, after two missed nightly backups.
--
-- Default privileges apply only to objects created LATER by avelren_migrator,
-- which is exactly the migration path.  Read-only, and scoped to the one role
-- whose entire purpose is to read everything.
ALTER DEFAULT PRIVILEGES FOR ROLE avelren_migrator IN SCHEMA public
    GRANT SELECT ON TABLES TO avelren_backup;

-- pg_dump also reads sequence state (last_value); without this a new sequence
-- breaks the dump the same way a new table would.
ALTER DEFAULT PRIVILEGES FOR ROLE avelren_migrator IN SCHEMA public
    GRANT SELECT ON SEQUENCES TO avelren_backup;
