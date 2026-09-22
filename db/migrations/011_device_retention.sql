-- Automatic privacy retention for inactive installations.
GRANT DELETE ON devices TO avelren_watchdog;
GRANT SELECT (last_seen) ON devices TO avelren_watchdog;
