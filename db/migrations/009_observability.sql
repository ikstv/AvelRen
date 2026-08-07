-- Durable-видимість вторинного конвеєра і чесний recovery (аудит OBS-1/OBS-2).
--
-- OBS-1. Збирач комітить спостереження (primary) окремо від alerts/ETA
-- (secondary) — це правильно (R-06): збій другорядного не сміє відкотити
-- незамінне спостереження. Але при падінні secondary код лише писав у лог,
-- і watchdog цього не бачив: observations свіжі, collector_runs.error чистий
-- (він про fetch), тож система виглядала здоровою, поки сповіщення тихо не
-- працювали. Додаємо статус secondary-фази в той самий рядок циклу.
--
--   derived_processed_at — фаза дійшла до кінця (успіх або зафіксована помилка);
--   derived_error        — фаза впала з винятком, і це має побачити watchdog.
--
-- NULL/NULL після grace-періоду = фаза не завершилась і виняток НЕ спрацював
-- (SIGKILL/OOM між primary-комітом і кінцем secondary) — теж проблема, яку
-- watchdog мусить помітити (B3).
ALTER TABLE collector_runs
    ADD COLUMN IF NOT EXISTS derived_processed_at timestamptz,
    ADD COLUMN IF NOT EXISTS derived_error        text;

-- Baseline для існуючих рядків: усе, що вже в БД до цієї міграції, вважаємо
-- історично обробленим — інакше watchdog одразу підняв би false-positive
-- «derived не оброблено» на всіх старих циклах (B3-rollout).
UPDATE collector_runs
SET derived_processed_at = time
WHERE derived_processed_at IS NULL;

-- OBS-2. Раніше watchdog ставив resolved_at і одразу «повідомляв» про
-- відновлення, ігноруючи результат надсилання. Якщо recovery-push падав,
-- тривога вже була закрита, а адмін нічого не знав, і повтору не було.
-- Розділяємо стан на три чіткі результати:
--   resolved_at           — проблема РЕАЛЬНО зникла (стан не бреше);
--   recovery_notified_at  — recovery ДОСТАВЛено (FCM прийняв);
--   recovery_abandoned_at — здалися, так і не доставивши (напр. немає адміна).
-- Notified і abandoned — різні поля саме тому, що PR про «стан не має брехати»:
-- по БД треба відрізняти «доставлено» від «здалися» (B2).
ALTER TABLE health_alerts
    ADD COLUMN IF NOT EXISTS recovery_notified_at  timestamptz,
    ADD COLUMN IF NOT EXISTS recovery_abandoned_at timestamptz;

-- Baseline: усі проблеми, закриті ДО цієї міграції, вважаємо вже
-- повідомленими — інакше новий watchdog розіслав би «AvelRen відновився» за
-- історичні resolved-тривоги (B1-rollout).
UPDATE health_alerts
SET recovery_notified_at = resolved_at
WHERE resolved_at IS NOT NULL
  AND recovery_notified_at IS NULL
  AND recovery_abandoned_at IS NULL;
