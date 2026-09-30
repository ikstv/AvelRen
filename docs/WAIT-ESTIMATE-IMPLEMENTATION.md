# Виконання контракту відсутньої оцінки

30.09.2026. Issue #70; legacy #111. Робоча гілка codex/wait-estimate-contract.
Специфікація й план — у docs/superpowers. Це незавершений кандидат,
не готовий до merge/deployment до підключення нового збереження й API.

## Крок 1

WorkloadItem приймає omitted/null як None, справжній 0 зберігає як 0;
статус виводиться з оцінки та не підміняється стороннім полем.
Тільки невід'ємний JSON integer; інші типи дають parse-помилку.
Новий wait_estimate.py централізує правило читання й виміряний ETA.
Позитивний paused wait збережено; paused/0 не дає ETA.

TDD: базові 201 unit пройшли; нові тести до правки — 31 failed/29 passed;
після правки весь unit набір — 234 passed. Два попередні deprecation
warnings Starlette/httpx/anyio зберігаються. Ruff успішний.
HTTP тільки MockTransport; production та upstream не використовувалися.

CORE-PROVENANCE зберігає вихідні SHA-256 і додає revision для моделі
та HTTP-тестів. Нові helper і unit-test файли — власний код проєкту.

## Крок 2 — кандидат, перевірка БД ще триває

Новий INSERT зберігає missing як технічний 0 з окремим статусом,
не гублячи кількість автомобілів. Міграція 015 додає статус із default
legacy_unknown та CHECK; старі міграції й історія не редагуються.
Schema contract піднімає вимогу нового runtime до 015.
CORE-PROVENANCE зберігає джерело та фіксує revisions db/schema_verify.

RED: isolated database CI на bf495415 — 2 нові тести failed, 22 passed
(колонка відсутня); локальні тести запису — 3 failed.
Після правки 237 unit passed, Ruff успішний. Compressed DDL, повний
pipeline, API/Android і restore/rollback ще не підтверджені.
Цей кандидат не готовий до merge або production deployment.

Мінімальний guard None у ETA перенесено до кроку 2, бо інакше
новий валідний вимір спричиняє TypeError у derived phase. Unit-тест
до правки відтворив timedelta(None); політика zero/paused ще незмінна.

### Блокер старої TimescaleDB

На commit 7405803 isolated database suite: 24 passed, включно з
test_status_migration_preserves_compressed_legacy; сучасний pin 2.30.1.
Але workflow database run 36733384982 завершився failure у репетиції
ops/timescale-upgrade-test.sh: вона застосовує всі migrations ще на
старому pin 2.17.2. Міграція 015 відхилена з повідомленням
`operation not supported on hypertables that have compression enabled`.
Лог містить весь SQL batch, тому конкретний ALTER ще не локалізований.

Це не failure збереження даних на 2.30.1 і не доказ стану production.
За STOP-критерієм погодженого плану подальшу реалізацію призупинено
до перегляду сумісності/порядку переходу. Не розпаковувати історію,
не пропускати upgrade gate і не застосовувати 015 до production.
Потрібно окремо погодити шлях: старі 001–014 на 2.17.2 → репетиція
оновлення extension/image → 015 на 2.30.1; або іншу сумісну схему.

Останній локальний набір після мінімального ETA guard: 238 passed,
2 попередні warnings; Ruff і provenance успішні. Новий pipeline test
ще потребує CI на commit, який містить цей test і guard.

### Перевірка погодженого порядку — 30.09.2026

Власник погодив ізольований порядок: 001–014 на 2.17.2 → image та
extension 2.30.1 → 015. Специфікацію й план уточнено; production GO
не наданий. Репетиція не змінює runtime schema gate або старі SQL.

CI на 18f680c, [database run 36735451208](https://github.com/ikstv/AvelRen-ORIGINAL/actions/runs/36735451208):
- database suite 25 passed, включно з missing pipeline/derived phase;
- старий compressed backup/restore успішний;
- image/extension upgrade зберіг raw/aggregate/compressed fingerprint;
- 015 після upgrade зберегла п'ять старих полів, compressed chunks,
  журнал 001–014 (включно з checksum/applied_at); до dump усі 50 статусів
  legacy_unknown;
- новий restore повернув ті самі 50 raw rows, 49 hourly buckets і 2
  compressed chunks; fingerprint та старий журнал збігаються;
- але `WHERE wait_time_status='legacy_unknown'` після restore повертає
  **1**, а не **50**. Gate зупинився з exit 1; пропуску assertions немає.

Гіпотеза: новий DEFAULT у вже compressed rows не переноситься штатним
dump/restore так само, як матеріалізовані значення. Розподіл решти
49 статусів і причина на рівні каталогу ще не перевірені; не називати
це доведеною втратою первинних wait/count даних або production-багом.
Потрібен перегляд способу збереження ознаки/restore-сумісності;
ніякого hidden UPDATE, decompress/backfill або послаблення gate.

Окремо API CI на 38d208b має 2 failed/51 passed/3 errors: старі prefix
fixtures 009/010/011/013 очікують запуск нового runtime без 015, який
тепер правильно відмовляється через SchemaTooOldError. Coverage старого
runtime й component-only optional-feature fallback треба зберегти при
оновленні fixtures; production gate не послаблювати. Повного green немає.

Локально на ed9024a: 238 unit passed, 2 попередні warnings; Ruff,
provenance, CI scopes (14 examples) успішні. PR #72 лишається draft.

### Причина та пропозиція — 30.09.2026, ще НЕ реалізовано

На d540300 [database run 36736530764](https://github.com/ikstv/AvelRen-ORIGINAL/actions/runs/36736530764)
повторив failure. Діагностика окремого disposable fixture:

| Зріз | Два compressed chunks | Uncompressed chunk | pg_attribute старих chunks |
| --- | --- | --- | --- |
| До dump, GROUP BY tableoid,status | legacy_unknown: 24+25 | legacy_unknown: 1 | atthasmissing=true, attmissingval={legacy_unknown} |
| Після restore, той самий SELECT | NULL: 24+25 | legacy_unknown: 1 | atthasmissing=false, attmissingval=NULL |

NOT NULL і DEFAULT у визначеннях старих chunks після restore лишаються,
але не замінюють втрачене missing-value metadata під час читання compressed
історії. Це доведений механізм цього fixture, не твердження про всі версії
TimescaleDB. PostgreSQL описує це metadata для доданих DEFAULT-колонок:
[pg_attribute](https://www.postgresql.org/docs/16/catalog-pg-attribute.html).

Додатково GROUP BY status із enable_columnarscan=off повертає лише
legacy_unknown:1 навіть ДО dump, тоді як GROUP BY tableoid,status показує
50. Отже, недостатньо виправити тільки restore: канонічне читання має
перевірятися різними query paths. Конкретний optimizer node ще не визначений;
ця розбіжність не доводить, що одного перемикання GUC досить для виправлення.

**Рекомендований перегляд збереження (потребує погодження):**

1. Додати nullable status без DEFAULT під час ADD COLUMN. Старі рядки
   фізично/логічно лишаються NULL; не створювати atthasmissing default і
   не переписувати/декомпресувати їх.
2. Окремим ALTER COLUMN SET DEFAULT 'legacy_unknown' забезпечити тільки
   майбутні INSERT старого collector без нового поля.
3. NULL у цьому внутрішньому полі означає лише legacy_unknown. Межа SQL/API
   нормалізує його через COALESCE; публічний status ніколи не стає NULL.
   Це не missing: новий collector завжди явно пише reported або missing.
4. CHECK допускає внутрішній legacy NULL, але відхиляє невідомі текстові
   значення, missing/nonzero та reported/negative. Інші старі поля незмінні.
5. Acceptance: перед/після dump і restore порівняти всі шість сирих полів
   та канонічні статуси, а не просто послабити старий assertion. Додати
   reported0, missing0, reported positive і старий INSERT до стиснених
   fixture; перевірити GROUP/WHERE/projection з scan налаштуваннями on/off,
   legacy ETA, backup SELECT і старий runtime. Ніякого production GO.

Альтернативи: окрема status-таблиця (більше join/FK/retention/restore
контрактів) або upstream fix з повторною перевіркою pin (зовнішня залежність,
не гарантія строків). Рекомендація nullable+нормалізація є гіпотезою для
нової ізольованої репетиції, не вже доведеним виправленням.

Product-код, міграція 015 та restore engine у цій діагностиці не змінені.
Потрібне погодження зміни внутрішнього контракту перед implementation.

### Погоджений nullable-контракт — реалізовано в кандидатові 30.09.2026

Попередній заголовок «ще НЕ реалізовано» описує минулий зріз.
Власник погодив nullable internal status; на d204056 кандидат 015 додає
колонку без DEFAULT, потім окремо встановлює default для майбутніх INSERT.
Helper нормалізує внутрішній NULL у публічний legacy_unknown. Історія
не переписується; міграції 001–014 незмінні. API/Android ще не підключені.

RED на 61e8c1e: helper 2 failed/28 passed; ізольований DB run 36737844434
дав 1 failed/24 passed — старий compressed status був legacy_unknown
замість очікуваного NULL. Лише після цього змінено draft 015, не застосовану
на production або іншій постійній БД.

На d204056 [run 36738550092](https://github.com/ikstv/AvelRen-ORIGINAL/actions/runs/36738550092)
пройшли старий restore, image/extension upgrade та 015 зі збереженням
історії/журналу/compression. До нового dump сценарій зупинився:
refresh_continuous_aggregate не дозволяє transaction block. Причина —
INSERT і CALL були в одному psql -c, не nullable DDL. На 8c5f9d4 CALL
винесено в окремий top-level запит, як у попередніх етапах сценарію.
Усі assertions збережені. Повний новий restore ще потребує результату CI.

Локально на 8c5f9d4: 242 unit passed, 2 попередні deprecation warnings;
Ruff/provenance/CI scopes (14 examples) і bash syntax успішні.
PR #72 лишається draft; production, APK, телефон і Play не змінювалися.

### STOP: nullable DDL не закрив query-path gate

На 8c5f9d4 [database run 36739447276](https://github.com/ikstv/AvelRen-ORIGINAL/actions/runs/36739447276)
database suite дала 25 passed. Старий compressed restore, image/extension
upgrade і nullable 015 зі збереженням історії/журналу пройшли.
Виправлений top-level refresh виконався. Однак assert_status_queries
зупинив сценарій **до нового dump**:

- scan=on пройшов групування `legacy_unknown|51`, `missing|1`, `reported|2`
  і перевірки WHERE (51 канонічний legacy, 50 внутрішніх NULL);
- scan=off повернув тільки `legacy_unknown|1` замість цих трьох груп.

Отже nullable-схема сама по собі не закрила приймання різних query paths.
Чи це дефект конкретного optimizer node, поведінка GUC або інший механізм,
поки не встановлено; даних для такого висновку недостатньо. Новий mixed
backup/restore не запускався, його успіх не заявляється. За STOP-критерієм
задача 2 незавершена; задачі 3–5 не початі. Потрібно переглянути контракт
після EXPLAIN/діагностики точного шляху читання, не прибирати assertions,
не додавати приховане decompress/backfill і не змінювати production.

На цьому самому head core, repository, watchdog і source SBOM CI успішні;
database та API workflows failure. Старі API prefix fixtures залишаються
окремим відомим блокером, а не доказом цього query-path дефекту.

### Розбір scan=off — 30.09.2026

На a1cf0ce [database run 36740545909](https://github.com/ikstv/AvelRen-ORIGINAL/actions/runs/36740545909)
EXPLAIN і чотири поєднання scan/indexscan дали однозначний результат у
цьому disposable fixture:

| columnarscan | columnarindexscan | count(*) | План compressed chunks |
| --- | --- | ---: | --- |
| on | on | 54 | ColumnarScan, три compressed chunks видимі |
| on | off | 54 | ColumnarScan, ті самі рядки видимі |
| off | on | 1 | Seq Scan rowstore частин; 53 compressed rows не читаються |
| off | off | 1 | Такий самий Seq Scan |

GROUP BY tableoid/status при `on` показав 24+25 старих compressed,
1 старий uncompressed, а також 1 legacy, 1 missing і 2 reported в новому
compressed chunk. При `off` лишився тільки uncompressed legacy1.
Це стосується навіть `count(*)`, без status-предиката. Отже відмінність
спричинена тим, що вимкнений ColumnarScan не читає compressed storage
цього fixture. Вона не є свідченням втрати 53 рядків від nullable DDL.

Критерій `scan=off` для compressed історії був хибним. У специфікації,
плані й gate його замінено на штатний ColumnarScan з обома режимами
columnarindexscan; `scan=off` збережено лише як пояснювальну діагностику.
Решта gate залишається: шість полів, GROUP/WHERE/projection, backup/restore,
старий journal, compressed chunks і ролі. Ця зміна критерію ще потребує
нового CI результату. Висновок обмежений перевіреним pin і fixture;
production GUC/версія не перевірялися.
