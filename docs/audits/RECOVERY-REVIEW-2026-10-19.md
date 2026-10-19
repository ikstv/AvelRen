# Сервер і повторний review recovery — 19.10.2026

## Read-only стан сервера

Перевірка 19.10.2026 о 15:27–15:40 UTC (18:27–18:40 за Києвом),
без зміни production файлів, контейнерів, state або timer.
Це датований зріз, а не deployment-приймання.

- Усі сім контейнерів працюють; restart count 0, OOM false, БД healthy.
- `/api/health`: HTTP 200, status/alert_channel/undelivered_alerts `ok`;
  вік останнього спостереження під час запиту — 6 секунд.
- PostgreSQL read-only: 1439 циклів за попередні 24 години, усі HTTP 200,
  без записаних помилок. Останні шість стартів розділені рівно 60 секундами;
  кожен містить 38 спостережень.
- На root disk вільно 22 GB; available RAM близько 2,7 GB.
- `avelren-backup.service` і recovery service завершилися помилкою.
  Timer enabled/active; наступний тоді запланований запуск —
  20.10 о 03:23:39 UTC. Повторні спроби 16–19.10 не завершили recovery.
- State: `recovery_required`, `failure_reason=ownership_unproven`,
  generation `16ef5926-236d-4d90-a857-b9173f217f3b`.
  Остання підтверджена paired copy — `20261015-032731`, завершена
  15.10 о 03:37:56 UTC. Це не нова restore-перевірка: прийнятий
  [off-host restore 14.10](PAIRED-LEGACY-RESTORE-2026-10-14.md)
  стосується іншої пари `20261014-102249`.
- SQLite відкрито лише через `mode=ro` та `query_only`: 1439 ACK,
  pending=started=0, останній цикл 15.10 о 15:49:39 UTC;
  capture_only=`0`, mode_ack відсутній. Свіжі SQL записи створює
  legacy direct writer; старий spool не є доказом роботи нового collector.

### Зафіксовані runtime pins

| Поле | Значення під час аудиту |
| --- | --- |
| Manifest | `/etc/avelren/collector-runtime.json` |
| Manifest SHA-256 | `0a7ffa2eb3097ff3832fa32de29b55d3aa8a4096326d5e759ae15a86899d79ac` |
| State SHA-256 | `07f1eaddbbc920a3d9bdebc150badfccf1e65781c325fd49e1507742c1e4a06e` |
| State/runtime root | `/var/lib/avelren-collector-runtime/c655b2a2e928d480431f26508a122f69a3e87411` (`state/` підкаталог) |
| Collector source | `4503477f334c72ab05409bf241779592d2fe0bf1` |
| Collector image | `sha256:40219d6c8ceee5a862382dbb62fe3df06181a20488635d47c5a965512eda9a72` |
| Collector container | `avelren-collector-1`, ID `3ca40a4899e080d3c004128a3111e8386a477e0f3f3a64cc0b25826c7cc5cc46` |
| StartedAt | `2026-10-15T15:51:15.565Z` |
| Project / network / volume | `avelren-collector-runtime` / `avelren_default` / `avelren_collector_spool_v1` |

Ці значення не можна використовувати для пізнішого запису без свіжої звірки.
Значення env, пароль БД, ключі та Device ID у звіт не включені.

## Source review PR #150

На початку перевірки main — `b009a275e058af9334ef02cd23039f06cebdd3a8`,
[PR #150](https://github.com/ikstv/AvelRen/pull/150) head —
`eb1d5ada4e7b54596ae7c513c625add996deb7f5`.
[CI 39017985551](https://github.com/ikstv/AvelRen/actions/runs/39017985551)
цього початкового head успішний: 11 jobs без skips, tested merge
`4f70a93e6440855e6b058cd1cf2338bdb82f2b09`.
Цей результат не приймає наступні виправлення.

Незалежний review migration/replay/restore не знайшов дефектів.
Review handoff відтворив і виправив три проблеми:

1. Collector міг змінити identity або зупинитися під час off/drain,
   але отримати terminal state. Тепер state, exact identity та running
   повторно перевіряються після drain і перед terminal commit.
2. Atomic manifest/rollback заміна синхронізувала state_dir замість
   каталогу призначення. Тепер fsync охоплює правильний каталог,
   SQL/SQLite safety-файли та capture/work каталоги до міграції.
3. Невдалий helper залишав зупинений контейнер із детермінованим ім'ям,
   блокуючи повторний finish/rollback. Повтор прибирає лише заново
   перевірені зупинені helpers власного generation/runtime; live і foreign
   helpers залишаються під забороною.

Регресії спочатку відтворили помилки, потім пройшли. Повторний незалежний
review виправлень — без зауважень. Реальний power-loss і live Docker
ACK timeout цим review не індукувалися; retry-тести використовують
справжні runtime/control методи з емульованою Docker boundary.

## Локальна перевірка і межі

- 31 handoff, 26 lease/state та 4 handoff daemon-wiring contracts — PASS,
  Linux container, network none, source mount read-only.
- 707 backend unit tests — PASS. Перший запуск із малим default tmpfs
  мав дві відмови через disk-space guard середовища; повний повтор із
  `/tmp:size=3g` пройшов. Backend між цим запуском і handoff fixes незмінний.
- Review image з початкового PR head зібрано з повного canonical backend:
  `sha256:5422ddd5c758ef004d0cd5a4a634166d6f0e93a7bdba7b7d0be0cbdc5c51c80f`.
  UID 10001, embedded SHA правильний; 58 installed Python modules і model
  JSON збігаються з source, installed model verification PASS.
  Це перевірочний образ гілки, не фінальний main deployment artifact.
- Нові hosted CI, merge, чистий main image/export, production handoff,
  нова paired copy та її off-host restore ще не прийняті цим записом.
  Android/телефон/Play цим етапом не перевірялися.

## Наступна дія

Завершити exact-head CI та інтеграцію PR #150, зібрати image з чистої main
і узгоджений пакет за [runbook](../../ops/COLLECTOR-RECOVERY-HANDOFF.md).
Після свіжого read-only preflight й окремого server GO — контрольований
handoff, п'ять природних циклів, нова paired copy та off-host restore.
Лише після їх приймання повернути timer. Наступний продуктовий gate —
телефонне приймання звуку, повторного «ОК» та cancel на APK з відомим SHA-256.
