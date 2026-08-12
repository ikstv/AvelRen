-- Application objects are owned by avelren_migrator.  Bootstrap has already
-- removed PUBLIC database and schema privileges; make object access explicit.

REVOKE ALL PRIVILEGES ON TABLE
    countries,
    checkpoints,
    observations,
    observations_hourly,
    collector_runs,
    devices,
    subscriptions,
    subscription_state,
    alerts,
    eta_targets,
    eta_alerts,
    health_alerts,
    notification_cancels,
    schema_migrations
FROM PUBLIC;

REVOKE ALL PRIVILEGES ON SEQUENCE
    alerts_id_seq,
    eta_alerts_id_seq,
    health_alerts_id_seq,
    notification_cancels_id_seq,
    subscriptions_id_seq,
    eta_targets_id_seq
FROM PUBLIC;

-- Backup: pg_dump needs data and sequence state, but never write capability.
GRANT SELECT ON TABLE
    countries,
    checkpoints,
    observations,
    observations_hourly,
    collector_runs,
    devices,
    subscriptions,
    subscription_state,
    alerts,
    eta_targets,
    eta_alerts,
    health_alerts,
    notification_cancels,
    schema_migrations
TO avelren_backup;
GRANT SELECT ON SEQUENCE
    alerts_id_seq,
    eta_alerts_id_seq,
    health_alerts_id_seq,
    notification_cancels_id_seq,
    subscriptions_id_seq,
    eta_targets_id_seq
TO avelren_backup;

-- Collector: source observations and the threshold/ETA lifecycle.
GRANT SELECT, INSERT, UPDATE ON TABLE
    countries,
    checkpoints,
    observations,
    collector_runs
TO avelren_collector;
GRANT SELECT ON TABLE
    subscriptions,
    subscription_state,
    alerts,
    eta_targets,
    eta_alerts
TO avelren_collector;
GRANT INSERT, UPDATE ON TABLE
    subscription_state,
    alerts,
    eta_targets,
    eta_alerts
TO avelren_collector;
GRANT INSERT ON TABLE notification_cancels TO avelren_collector;
GRANT SELECT (kind, alert_id) ON notification_cancels TO avelren_collector;
GRANT USAGE ON SEQUENCE
    alerts_id_seq,
    eta_alerts_id_seq,
    notification_cancels_id_seq
TO avelren_collector;

-- Notifier: delivery lifecycle, scoped device token maintenance, and outbox cleanup.
GRANT SELECT ON TABLE
    alerts,
    eta_alerts,
    subscriptions,
    eta_targets,
    checkpoints,
    notification_cancels
TO avelren_notifier;
GRANT SELECT (id, fcm_token), UPDATE (fcm_token) ON devices TO avelren_notifier;
GRANT UPDATE (last_sent_at, send_count) ON alerts, eta_alerts TO avelren_notifier;
GRANT UPDATE (attempt_count, last_attempt_at, accepted_at, abandoned_at)
    ON notification_cancels TO avelren_notifier;
GRANT DELETE ON notification_cancels TO avelren_notifier;

-- Watchdog: read health inputs and own only the health-alert lifecycle.
GRANT SELECT ON observations, collector_runs, health_alerts TO avelren_watchdog;
GRANT SELECT (id, is_admin, fcm_token) ON devices TO avelren_watchdog;
-- Мертвий адмін-токен FCM watchdog має самостійно гасити (`UPDATE devices SET
-- fcm_token = NULL`), інакше кожен health-alert ретраїть один і той самий
-- мертвий токен щоциклу вічно. Раніше цього grant'у не було, і M-10-fix у
-- коді (watchdog.py:313) на practice падав із permission denied під роллю
-- avelren_watchdog — регресія M-10 з independent review PR #29.
GRANT UPDATE (fcm_token) ON devices TO avelren_watchdog;
GRANT INSERT, UPDATE ON health_alerts TO avelren_watchdog;
GRANT USAGE ON SEQUENCE health_alerts_id_seq TO avelren_watchdog;

-- API: public reads, endpoint-authorized lifecycle writes, and no whole-device access.
GRANT SELECT ON TABLE
    countries,
    checkpoints,
    observations,
    observations_hourly,
    collector_runs,
    subscriptions,
    alerts,
    eta_targets,
    eta_alerts,
    health_alerts
TO avelren_api;
GRANT SELECT (id, fcm_token, platform, secret_hash, is_admin, last_seen),
    INSERT (fcm_token, platform, secret_hash),
    UPDATE (fcm_token, last_seen)
ON devices TO avelren_api;
GRANT INSERT, UPDATE, DELETE ON subscriptions, eta_targets TO avelren_api;
GRANT UPDATE (status, acknowledged_at) ON alerts, eta_alerts TO avelren_api;
GRANT INSERT ON notification_cancels TO avelren_api;
GRANT SELECT (kind, alert_id) ON notification_cancels TO avelren_api;
GRANT USAGE ON SEQUENCE
    subscriptions_id_seq,
    eta_targets_id_seq,
    notification_cancels_id_seq
TO avelren_api;

-- New migrator-owned objects are private until a future migration grants access.
ALTER DEFAULT PRIVILEGES FOR ROLE avelren_migrator
    REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE avelren_migrator
    REVOKE USAGE ON TYPES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE avelren_migrator IN SCHEMA public
    REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE avelren_migrator IN SCHEMA public
    REVOKE ALL ON SEQUENCES FROM PUBLIC;
