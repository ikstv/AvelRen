# Звірка надісланого аудиту — 12.10.2026

Вхід: аудит AvelRen, переданий власником12.10 як «Вставлений текст.txt». Контрольний main eed0cb0f5a337e88467943017bbca3a04d2593e2. Звірено код і fresh GitHub API. Production не опитували; SQL/API/конкурентні тести тут не запускали. Sandbox архів зі звіту недоступний у цій сесії, його вміст не засвідчується.

## Підтверджені знахідки

| Пункт | Доказ | Наступна робота |
| --- | --- | --- |
| Переприв’язування FCM | subscriptions_api.py create_device/update_token очищають token попереднього device без його credentials | Окремий conflict/reinstall/lost-secret design, Android compatibility та API/PostgreSQL concurrency tests |
| Stale dead token | notifier.py _disable_device: WHERE id; normal/cancel callers передають лише id | Compare-and-clear exact sent token, реальні PostgreSQL regression tests |
| Cancel stale-token outcome | _send_cancels одразу mark_abandoned після dead token | За вже оновленого token не вважати новий dead; зберегти bounded retry/age policy |
| main protection | Fresh branches/main: protected=false, checks enforcement off | Always-running aggregate gate, enforceable protection, failed PR cannot merge |
| Rulesets тариф | Fresh API403: GitHub Pro або інша доступна private-repo можливість | Рішення власника про тариф; privacy/billing не змінювати. CI gate без enforcement не дорівнює protection |
| Застарілий PR72 | MERGED02.10, d134c0b; server status/missing і Android wait_estimate у main | Не повторювати DTO/UI перенос; holdout/recovery/phone acceptance окремо |

Наявний test_repeat_registration_with_known_token_does_not_leak_device_id перевіряє credentials/subscriptions isolation, але не збереження push-прив’язки старого device. Передумова першого дефекту: чужий FCM token вже відомий; захоплення чужих subscriptions не доведене.

Registration tokens мають бути secret: [Firebase](https://firebase.google.com/docs/cloud-messaging/server-environment). Коментар token is not a secret потрібно виправити; token не є installation credential. [PostgreSQL Read Committed](https://www.postgresql.org/docs/16/transaction-iso.html) обґрунтовує conditional UPDATE, але не замінює real project tests.

## Залишки перенесення, не нові дефекти

DB executor прийнятий PR121; його повторно не реалізовувати. [Maintenance plan](../superpowers/plans/2026-10-12-postgres-production-maintenance.md) очікує перегляду власником. Actual adapter, DSN cutover, runtime provenance та operational acceptance попереду. Legacy collector/watchdog superuser — лише датований серверний audit11.10, не свіжа перевірка сьогодні.

Актуальний off-host backup/checksum, isolated PostgreSQL/SQLite restore/spool reconciliation та виміряні RPO/RTO не прийняті. Backup timer або synthetic CI не закривають цей пункт. SBOM не є CVE scan чи доказом actual production image. Android CI відсутній на DB-only head не означає Android failure; APK/телефон/Play окремі gates.

## Конкретний перший fix для перегляду

Bounded notifier fix: _disable_device(conn, device_id, sent_token) -> bool. UPDATE devices SET fcm_token=NULL WHERE id=%s AND fcm_token=%s; результат за changed rows. Normal pending alert зберігається. Cancel abandoned лише якщо exact token справді очищено; stale response використовує existing bounded retry/age policy.

Real PostgreSQL regression: T1 прочитаний → FCM call suspended → інша connection commits T2 → FCM dead T1; T2 збережено. Current dead T1 очищається. Обидва normal/cancel paths, no live FCM. Source поки не змінений.

Окремий token ownership design не повинен від’єднувати чинного власника за одним token або повертати чужі credentials. Reinstall/lost-secret recovery потребує явного контракту; не вводити409 без звірки Android registration flow.

Порядок: notifier regression/fix; token ownership design; aggregate gate/protection; backup/runtime/maintenance acceptance; окремі production GO/DSN/release/monitor. Не видаляти старі repositories до фінального приймання.
