-- Durable-видимість вторинного конвеєра і чесний recovery (аудит OBS-1/OBS-2).
--
-- OBS-1. Збирач комітить спостереження (primary) окремо від alerts/ETA
-- (secondary) — це правильно (R-06): збій другорядного не сміє відкотити
-- незамінне спостереження. Але при падінні secondary код лише писав у лог,
-- і watchdog цього не бачив: observations свіжі, collector_runs.error чистий
-- (він про fetch), тож система виглядала здоровою, поки сповіщення тихо не
-- працювали. Додаємо статус secondary-фази в той самий рядок циклу.
ALTER TABLE collector_runs
    ADD COLUMN IF NOT EXISTS derived_processed_at timestamptz,
    ADD COLUMN IF NOT EXISTS derived_error        text;

-- OBS-2. Раніше watchdog ставив resolved_at і одразу «повідомляв» про
-- відновлення, ігноруючи результат надсилання. Якщо recovery-push падав,
-- тривога вже була закрита, а адмін нічого не знав, і повтору не було.
-- Розділяємо: resolved_at — проблема РЕАЛЬНО зникла (стан не бреше);
-- recovery_notified_at — адміну про це доставлено. Друге ретраїться окремо,
-- поки не вийде.
ALTER TABLE health_alerts
    ADD COLUMN IF NOT EXISTS recovery_notified_at timestamptz;
