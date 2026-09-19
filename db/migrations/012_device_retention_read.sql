-- The retention DELETE predicate reads last_seen under the watchdog role.
GRANT SELECT (last_seen) ON devices TO avelren_watchdog;
