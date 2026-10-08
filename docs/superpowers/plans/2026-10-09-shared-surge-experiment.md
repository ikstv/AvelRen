# Спільний прогноз і відтворення сповіщень — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Власник раніше обрав виконання самим агентом у цій сесії; цей спосіб зберігається.

**Goal:** Побудувати локальний відтворюваний експеримент із двома оцінювачами та п'ятьма кандидатами, з окремими результатами всіх 38 черг.

**Architecture:** Окремий Python-пакет дослідження читає дозволені незмінні файли, створює причинні ознаки й мітки, відтворює поточну політику та формує звіт. Чистий replay перевіряється на паритет із чинними функціями в disposable БД; транспорт FCM підмінений. Архівний evaluator і runtime залишаються незмінними.

**Tech Stack:** Python 3.12+, NumPy 2.5.2, SciPy 1.18.1, pytest 9.1.1; наявні psycopg/TimescaleDB і локальні Compose-тести. Дослідницькі залежності мають окремий lock; жодного додавання до production requirements.

**Spec:** [Уточнена специфікація](../specs/2026-10-09-shared-surge-experiment-design.md). Попередню редакцію погоджено 09.10.2026; уточнення за review власника та цей план очікують спільного погодження. Навчання цим review не дозволене.

## Global Constraints

- Чинна frozen-модель: виключно ID 1, 6, 17, 29; інші 34 ID — «не застосовується».
- Новий спільний кандидат може використовувати придатні дані всіх 38 черг; оцінювання кожної окреме.
- Погодження дизайну не дозволяє переносити додаткову історію або розгортати новий прогноз.
- Frozen-модель, її незалежний тест, експериментальні сповіщення, позначка «Функція в розробці» й голосові фрази незмінні.
- Подія: чистий приріст ≥20 за 5 хв; допуск ±30 с, внутрішні gap ≤90 с, кластер початків ≤30 хв.
- +200 за ≤20 хв — окремий зріз із картою перекриття; не сума з основними подіями.
- Невідомі мітки не стають негативним класом; без знаменника метрика має null і причину.
- Дані, credentials, історія пристроїв і production DSN не потрапляють у Git або CI.
- Тести не звертаються до єЧерги або живого FCM; лише один штатний collector на production.
- Локальні DB-тести використовують наявний випадковий Compose project і tmpfs, без production volumes.
- Незмінні межі старого тесту: origins 02.10–09.10, майбутнє до 10.10.2026 00:05 за Києвом; дата сама по собі не дозволяє оцінювання без даних.
- Навчання не починається до готовності й перевірки replay, manifest і погодження цього плану.

## Review Focus

1. Повторення місцевої години при переході на зимовий час: зберегти різні UTC-години, не змішати два прогнози; Task 4.
2. Дубль, NaN, bool замість count або невірний hash: відмова до ознак і fit без друку вмісту рядка; Task 1.
3. Черга без позитивних подій або навчання з одним класом: null/причина, а не 100% чи вигадана модель; Tasks 3, 6.
4. Межі періоду, прогрів і відкритий епізод: явні cohorts/carry-in/censored; модель не прогнозує до train_end; Tasks 2, 4, 7.
5. ACK, дубль FCM і нова підписка в активному епізоді: повтори не множать TP, ACK не відновлює голос; Task 5.

## Послідовність, файли та дозволи

Tasks 1–5 створюють і перевіряють стенд без нових даних. Tasks 6–8
додають кандидатів, метрики та частковий запуск на вже дозволених файлах.
Task 9 готує конкретний запит на перенесення; до дозволу на нього не
виконується завантаження. Task 10 завершує порівняння після отримання
даних. CI — лише синтетичні тести, без навчання на production-історії.

Нові модулі — `tools/surge_experiment/`; тести — `tests/research/`.
Виняток: parity-тест із реальною локальною БД у
`services/backend/tests/database/api/test_surge_replay_parity.py`.
CLI — `python -m tools.surge_experiment`; результати — новий каталог у
`dist/shared-surge-experiment/`. Сирі й похідні навчальні ряди не публікуються.

## Зафіксовані рішення експерименту v1

**Періоди:** train до 18.09 00:00; selection 18.09–25.09; development
25.09–02.10.2026. Усі межі за Києвом, праві виключні. Purge за фактичним
кінцем залежностей мітки, включно з підтвердженням її епізоду. Дані після
02.10 не впливають на fit, нормування, ваги, поріг або вибір кандидата.

**Час і початковий стан:** безперервний replay має
`replay_start=16.09.2026 22:00` за Києвом,
`warmup_duration=26h`, `forecast_enabled_from=18.09.2026 00:00`.
Історія ознак може читатися ще на 4 год 3 хв раніше replay_start.
Початково `SurgeState(None,None,true,None)`, last_forecast_hour=null,
порожні attempts/ACK; синтетичні підписки активні від replay_start.
До forecast_enabled_from обробляються факти й якість, без прогнозів
кандидатів, навчених до train_end. Параметри кожного trial незмінні
в усьому потоці. На 25.09 стан не скидається; carry-in не створює
нового повідомлення. Frozen на selection — лише історичний довідковий
результат: його поріг уже добирався на цьому періоді, не незалежний тест.

**Області основних метрик:** для selection/development частини `[S,E)` з
`label_cutoff=E` задаються область початкових попереджень
`[S,E-24h-35m)` та область подій `[S+24h,E-23h-35m)`.
Таким чином весь номінальний інтервал 1–24 год до кожної оцінюваної
події міститься в області попереджень; пропуски джерела його не звужують.
35 хв — мінімальний запас, фактичний кінець залежності об'єднаного
епізоду перевіряється додатково. Незавершені або сумнівні мітки мають
окремі причини. Межі переводяться в UTC; 1/24 год і 35 хв — elapsed duration.
Для precision подія може бути поза областю recall, але в початковому
горизонті попередження; тому `tp_alerts` і `matched_events` не підміняють
одне одного. Для recall враховуються лише зіставлені події його області.
Увесь решта потік залишається в edge/carry-in таблиці з причинами:
штучно обрізаний край не FN, реальна нестача минулих даних усередині — FN.
Це консервативні однакові межі порівнянь розробки без читання майбутнього
наступної частини; вони фіксуються до перегляду результатів.
Для наступного незалежного тесту область попереджень — усі 28 повних
діб `[S,E)`, область подій — `[S+24h,E+1h)`; потрібні спостереження
щонайменше до `E+24h+35m` і фактичне підтвердження завершеності міток.
Прогрів починається `S-26h`, прогнози — не раніше фактичного freeze.
Ці додаткові майбутні дані ще не дозволено переносити. Архівний frozen
evaluator зберігає власні межі без заміни.

**Вхід навчання:** перший придатний origin кожної місцевої години за
тими самими past-quality/cadence правилами, що й базовий replay.
Його будує data-only helper без моделі, щоб не створити циклу
залежностей training ↔ replay. Майбутнє не впливає на вибір. Frozen має незмінні
ознаки; нові кандидати використовують 11 ознак:
`(count-median_q)/scale_q, d5/scale_q, d10/scale_q, d20/scale_q,
d60/scale_q, (d5-d10/2)/scale_q, paused, sin_day, cos_day, sin_week, cos_week`.
`median_q` і `scale_q=max(1,Q75(count)-Q25(count))` — тільки train.
Календар за Києвом; усі лаги/довга якість — за контрактом frozen.

**Ваги fit:** позитивні origins групуються за найранішою підтвердженою
подією свого горизонту, негативні — за ID і місцевим днем. Кожна група
має суму ваг 1, потім кожна черга нормується до суми 1. Ваги всіх черг
разом нормуються до суми 1. Невідомі/сумнівні приклади не беруть участі
у fit. Реальний часовий потік selection/development не зменшується.

**Кандидати:**

- Calendar: зважена частота позитивного класу в клітинці
  `(queue_id, weekday, hour)`, згладжена 10 псевдоспостереженнями до
  глобальної train-частоти `(sum(w*y)+1)/(sum(w)+2)`; для цієї формули
  fit-ваги спочатку домасштабовані до кількості придатних train origins.
- Trend: `sigmoid(clip((d5 + (d5-d10/2))/scale_q,-30,30))`; інших
  коефіцієнтів, навчання або підбору ознак немає.
- Frozen: незмінні JSON, support і threshold із репозиторію.
- Pooled: логістична регресія на 11 ознаках із intercept і 38 окремими
  queue intercept offsets. Weighted mean log-loss + `lambda/2 * ||beta||²`
  + `10*lambda/2 * ||queue_offsets||²`; загальний intercept не штрафується.
- Chop-local: та сама логістична регресія на 11 ознаках лише ID 17,
  без queue offsets. Її результат порівнюється з іншими тільки на Чопі.

**Малий добір:** lambda ∈ `{0.001,0.01,0.1}` для двох логістичних
моделей. Початкові коефіцієнти 0, SciPy L-BFGS-B, maxiter 1000,
gtol `1e-8`, один BLAS-потік, seed `20261009`. Невдала збіжність
позначає кандидата неготовим; прихованого повтору з іншими параметрами немає.
Пороги нових кандидатів: `{0.05,0.10,…,0.95,0.99}`; frozen не підбирається.

**Вибір:** лише selection і базовий replay. Для кожного кандидата
ранжувати визначені оцінки за `min(precision, overall_recall)`, потім
їх гармонійним середнім, меншою кількістю FP, вищим порогом, більшою
lambda, стабільним ID. Гармонійне середнє є допоміжним ranking score:
через різні часові cohorts його не називають стандартним F1.
Спроба з невизначеною P або R не перемагає. Порівняння calendar/trend/pooled
за всім однаковим набором доступних ID; frozen — лише спільні чотири,
Chop-local — лише Чоп. Часткові 4-ID результати не обирають переможця
для всіх 38. Повний звіт містить усі спроби, не лише переможця.
Нові параметри після перегляду development означають нову версію експерименту.

**Довірчі оцінки:** після незмінного chronological matching агрегувати
внески precision за днем alert_created_at, recall — за днем onset_at.
Основна оцінка невизначеності — moving-block bootstrap цих добових
векторів: блок 7 послідовних київських діб, 2000 повторів, seed 20261009,
двобічні percentile-квантілі 2,5%/97,5%. Брати випадкові допустимі початки
блоків із поверненням, з'єднувати до довжини вихідного періоду й обрізати
надлишок. Однакові індекси днів для всіх ID і порівнюваних кандидатів;
внутрішній replay або matching на переставлених днях не повторювати.
Це оцінка за припущенням обмеженої часової залежності, не її доказ.
Менше 28 повних діб, менше 90% повторів із ненульовим знаменником
або вироджений розподіл → CI=null із відповідною причиною.
Отже тижневі selection/development не отримають удавано точний інтервал.
Окремий діагностичний Clopper–Pearson 95% можливий лише з явною позначкою
«припускає незалежні випробування»; він не замінює блокову оцінку.
Реалізацію exact API звіряти з [SciPy proportion_ci](https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats._result_classes.BinomTestResult.proportion_ci.html);
жоден вузький або вироджений інтервал не є автоматичним прийманням 99%.

**Завершення без приймання:** якщо на development обраний за selection
кандидат не має одночасно P≥0.99 і загальний R≥0.99 — `criterion_not_met`;
невизначені метрики — `insufficient_evidence`. Показати всі trials,
завершити перебір без додаткового fit, зміни порога або CANDIDATE-FREEZE.
Навіть P/R≥0.99 тут означає лише придатність до окремого майбутнього
випробування, не підтверджену якість. По кожному ID показати той самий
критерій; загальний результат не є твердженням «99% на всіх 38».
Чинний експеримент продовжує працювати за попереднім погодженням.

### Task 1: Вхідний контракт і захист від непогодженого запуску

**Files:** create `tools/surge_experiment/__init__.py`, `contracts.py`,
`data.py`, `manifest.py`, `__main__.py` у цьому пакеті;
`tests/research/conftest.py`, `tests/research/test_surge_data.py`;
`.github/workflows/research.yml`; modify `scripts/verify_ci_scopes.py`.

**Interfaces:** `ObservationRow(queue_id:int,time:datetime,count:int,paused:bool)`;
`Dataset(rows:dict[int,list[ObservationRow]],source_hashes:dict[str,str])`;
`Manifest` — frozen dataclass з усіма значеннями розділу v1, включно
з початковим станом, timestamps cohorts, warmup, CI і stop rule;
`load_dataset(paths:list[Path],expected_hashes:dict[str,str])->Dataset`;
`validate_manifest(config:dict)->Manifest`. CLI читає лише локальні файли.

- [ ] Написати тести: `test_hash_mismatch_fails_before_parse`,
  `test_duplicate_and_invalid_count_rejected`, `test_missing_parameter_blocks_fit`,
  `test_no_network_or_production_credentials`. Очікування: `ValueError`,
  лічильник викликів fit дорівнює 0; bool/NaN/негативний count не допускаються.
- [ ] Запустити `python -m pytest tests/research/test_surge_data.py -q`;
  підтвердити FAIL через відсутній модуль/інтерфейс.
- [ ] Реалізувати інтерфейси, UTC-нормалізацію, унікальність `(ID,time)`,
  детерміноване сортування та відмову від output, який уже існує.
  У conftest заборонити зовнішні sockets/HTTP/DB; дозволити loopback для asyncio.
- [ ] Додати окремий research CI на Python 3.12 з наявними pinned Actions.
  Paths: `tools/surge_experiment/**`, `tests/research/**`,
  `services/backend/src/avelren/surge_*.py`, `services/backend/src/avelren/models/**`,
  `services/backend/requirements.lock`, `services/backend/pytest.ini`,
  `.github/workflows/research.yml`, `scripts/verify_ci_scopes.py`.
  Додаткові реально імпортовані залежності включити явно після звірки imports.
  CI не читає `dist` і не тренує реальні моделі. Матриця verify_ci_scopes
  має перевіряти research-код і всі його імпортовані залежності.
- [ ] Повторити pytest і `python scripts/verify_ci_scopes.py`; PASS.
  Commit: `test: визначити ізольований контракт дослідження прогнозу`.

### Task 2: Події, тризначні мітки та часові залежності

**Files:** create `tools/surge_experiment/events.py`, `labels.py`, `splits.py`;
`tests/research/test_surge_labels.py`.

**Interfaces:** `Event(event_id,queue_id,onset_at,confirmed_at,last_qualifying_start,dependency_end,questionable)`;
`WindowQuality(past_valid:bool,future_known:bool,unknown_intervals:tuple[tuple[datetime,datetime],...])`;
`Label(value:int|None,event_ids:tuple[str,...],dependency_end:datetime,reason:str|None)`;
`build_events(rows,cutoff)->list[Event]`;
`label_origin(origin,events,quality:WindowQuality)->Label`;
`purged_origins(origins,labels,start,end)->list[datetime]`.

- [ ] Тести: `test_30minute_merge_boundary`, `test_gap_is_unknown_not_zero`,
  `test_positive_survives_unrelated_unknown_future`, `test_boundary_purges_label_dependency`,
  `test_large_jump_overlap_is_not_added`, `test_open_episode_is_censored`,
  `test_onset_and_confirmation_are_distinct`.
  Фікстури: gap 91 с → unknown; 30 хв → один епізод, 30 хв + 1 с → два;
  край до останнього qualifying start + 35 хв → незавершений;
  origin із dependency_end ≥ split_end не потрапляє в попередню частину.
  Вікно 10:00–10:05: onset=10:00, confirmed=10:05, попередження 10:03
  має lead=-3 хв і не є завчасним прогнозом.
  ```python
  assert event.onset_at == t1000
  assert event.confirmed_at == t1005
  assert (event.onset_at - t1003).total_seconds() == -180
  ```
- [ ] Запустити `python -m pytest tests/research/test_surge_labels.py -q`; FAIL.
- [ ] Відтворити чинні лаги та clustering з паритетом до `_lag_index`.
  Для +200 використати будь-які дві точки з dt ≤1200 с без gap >90 с;
  створити карту перекриття по ID/часу. Для unknown зберегти точні
  інтервали й множини зачеплених origins. Джерело аудиту переносити
  лише з атрибуцією і перевіркою SHA, не імпортом із `dist`.
- [ ] Повторити тести; PASS. Commit: `feat: додати мітки подій без витоку майбутнього`.

### Task 3: Причинні ознаки й навчальні ваги

**Files:** create `tools/surge_experiment/features.py`;
`tests/research/test_surge_features.py`.

**Interfaces:** `FeatureRow(queue_id,origin,values:tuple[float,...],label:Label,weight:float)`;
`fit_scales(dataset,train_end)->dict[int,tuple[float,float]]`;
`features_at(rows,origin,scales)->tuple[float,...]|None`;
`training_rows(dataset,manifest)->list[FeatureRow]`.

- [ ] Тести: `test_future_spike_does_not_change_past_features`,
  `test_weights_do_not_count_overlapping_origins_as_events`,
  `test_zero_event_queue_keeps_known_negatives`, `test_constant_scale_is_one`.
  Додавання майбутнього count=100000 не змінює попередні ознаки/масштаби;
  кожна черга має однакову суму ваг, unknown має нуль участі у fit.
- [ ] Запустити `python -m pytest tests/research/test_surge_features.py -q`; FAIL.
- [ ] Реалізувати 11 ознак, навчальні ваги й quality: 5/10/20/60 хв
  gap ≤90 с; 120/240 хв gap ≤300 с, coverage ≥95%, endpoint ±30 с.
  Лаги доступні лише з минулого; для непідготовленої черги повернути
  недоступність, не масштаб від майбутніх даних.
- [ ] Повторити тести; PASS. Commit: `feat: додати причинні ознаки спільного прогнозу`.

### Task 4: Replay worker та незмінний frozen adapter

**Files:** create `tools/surge_experiment/replay.py`, `frozen.py`, `legacy.py`;
`tests/research/test_surge_replay.py`, `test_surge_legacy.py`.

**Interfaces:** `Candidate.score(queue_id,rows,origin)->ScoreResult`;
`ScoreResult(score:float|None,threshold:float|None,status:str,reason:str|None)`;
`ReplayResult(decisions:list[dict],alerts:list[dict],availability:list[dict])`;
`replay(dataset,candidate,manifest,latency_seconds:int)->ReplayResult`;
`run_legacy(data_dir:Path,start:datetime,end:datetime,output:Path)->dict`.

- [ ] Тести: `test_frozen_other_34_ids_not_applicable_without_predict_call`,
  `test_retry_after_new_observation_same_hour`, `test_success_once_per_hour`,
  `test_ticks_without_data_expire_state`, `test_dst_repeated_hour_distinct_utc`,
  `test_future_rows_invisible_before_available_at`,
  `test_model_never_runs_before_train_end`, `test_carry_in_preserves_state_and_ack`.
  Unsupported ID 14: усі прогнозні метрики null; spy predict_surge не викликано.
  Для 25.10.2026 дві локальні 03:00 мають різні UTC-ключі години.
- [ ] Запустити `python -m pytest tests/research/test_surge_replay.py tests/research/test_surge_legacy.py -q`; FAIL.
- [ ] Реалізувати ticks кожної UTC-хвилини, latency 0/60 с, freshness,
  state/expiry/rearm через `advance_state`. Пороговий адаптер кандидатів
  подає лише еквівалентний сигнал вище/нижче незмінної runtime-константи;
  оригінальний score/threshold зберігає окремо. Frozen передає свій score
  без перетворень. Початок/стан/26 год прогріву — за manifest v1;
  один безперервний потік не скидається на межі. Carry-in не дублюється,
  до train_end немає ретроспективних прогнозів навченого кандидата.
- [ ] Legacy запускається окремим локальним процесом. Для переносимості
  дозволена лише AST-заміна точного hardcoded data-root архівного runner;
  AST після маскування цього літерала має збігатися. Оригінальні файл,
  hash-перевірки й формули незмінні; виправлення root документується.
  У CI — структурна перевірка адаптера; фактичний паритет на приватних
  дозволених файлах виконується локально в Task 8 до 02.10.
- [ ] Повторити тести; PASS. Commit: `feat: відтворити worker і зберегти frozen-протокол`.

### Task 5: Паритет із БД та повний механізм сповіщень

**Files:** create `services/backend/tests/database/api/test_surge_replay_parity.py`;
modify `scripts/test_database.sh` (додати файл до suite surge);
create `tests/research/test_surge_delivery_accounting.py`.

**Interfaces:** використати `replay`/`ReplayResult`; реальні
`process_checkpoint`, `reserve_attempt`, `accept_attempt`, ACK API,
notifier cancel; тільки synthetic FCM і deterministic clock.

- [ ] Тести: `test_replay_matches_database_transitions`,
  `test_ack_and_duplicate_do_not_multiply_alerts`,
  `test_resubscribe_preserves_ack`, `test_five_queues_cancel_isolated`,
  `test_unknown_transport_retry_same_attempt`.
  Перевіряти події/закриття/predictions і IDs після нормалізації,
  повтор через 300 с, retry через 60 с із тим самим attempt ID,
  відсутність повтору після ACK/expiry та окремий cancel по черзі.
- [ ] Запустити `bash scripts/test_database.sh surge` з Git Bash на Windows;
  початковий FAIL має бути через відсутню parity-поведінку, не Docker/setup.
- [ ] Підключити адаптер replay до сценаріїв існуючого end-to-end тесту,
  не змінюючи runtime. У кожному сценарії порівняти чисте відтворення
  та справжні транзакційні переходи. Підписки — синтетичні; фактичні
  користувачі й Firebase не завантажуються.
- [ ] Повторити suite surge та локальний unit accounting; PASS.
  Якщо Docker недоступний, завершити unit-роботу, але навчання не запускати
  до цього gate. Commit: `test: підтвердити паритет сповіщень на локальній БД`.

### Task 6: П'ять кандидатів і обмежений добір

**Files:** create `tools/surge_experiment/candidates.py`, `training.py`,
`requirements.in`, `requirements.lock`; `tests/research/test_surge_training.py`;
modify research workflow для окремого hashed lock.

**Interfaces:** `FitArtifact(candidate_id,parameters:dict,train_hashes:dict,status:str)`;
`fit_candidate(candidate_id,rows:list[FeatureRow],manifest:Manifest)->FitArtifact`;
`load_candidate(artifact:FitArtifact)->Candidate`;
`select_trial(trials:list[dict])->dict|None`.

- [ ] Тести: `test_training_cutoff_and_unknown_exclusion`,
  `test_single_class_fit_has_explicit_reason`, `test_regularization_penalizes_queue_offsets`,
  `test_repeat_fit_is_deterministic`, `test_selection_uses_replay_not_row_accuracy`.
  Один клас → `insufficient_training_classes`; дані після train_end
  не змінюють coefficients; у ranking не бере участі development.
- [ ] Запустити `python -m pytest tests/research/test_surge_training.py -q`; FAIL.
- [ ] Реалізувати точні формули/сітки v1. NumPy/SciPy імпортуються лише
  в навчальних модулях: DB parity не потребує цих пакетів. Створити lock
  з hashes для окремого research venv, без змін backend lock. Перевірити
  колеса Python 3.12 для поточної Windows і CI Linux до фіксації lock.
- [ ] Повторити тести й `python -m pip check` у research venv; PASS.
  Commit: `feat: додати обмежене порівняння кандидатів прогнозу`.

### Task 7: Метрики подій, недоступність і звіт

**Files:** create `tools/surge_experiment/metrics.py`, `report.py`;
`tests/research/test_surge_metrics.py`, `test_surge_report.py`.

**Interfaces:** `evaluate_alerts(result:ReplayResult,events:list[Event],manifest)->dict`;
`report_rows(results:list[dict],queue_ids:tuple[int,...])->list[dict]`;
`write_report(results:list[dict],output_dir:Path)->None`.

- [ ] Тести: `test_one_alert_matches_only_one_event`,
  `test_cancel_does_not_remove_false_alert`, `test_no_events_recall_null`,
  `test_no_alerts_precision_null`, `test_unknown_horizon_not_fp`,
  `test_positive_match_with_partial_unknown_is_tp`, `test_end_censor_not_fn`,
  `test_38_by_5_rows_preserve_not_applicable`, `test_unknown_overlap_union`,
  `test_three_initial_alerts_one_event_gives_two_fp`,
  `test_matching_ties_ignore_input_order`, `test_boundary_differs_from_real_gap`,
  `test_separate_precision_and_recall_cohorts`, `test_exact_phase_cohorts`,
  `test_ci_short_or_degenerate_null`,
  `test_unmet_target_stops_without_extra_fit`, `test_twelve_and_seven_remain_distinct`.
  5 кандидатів ×38 ID →190 рядків навіть за часткових даних; повтори
  не збільшують TP. Знаменник FP-rate — об'єднання хвилинних tick-інтервалів
  області попереджень із повністю відомим майбутнім, незалежно від score;
  FP-rate=FP/assessable_seconds*30*86400, при нулі — null.
  Одна подія/3 початкові тривоги: TP=1, FP=2, P=1/3;
  одна тривога/2 нагадування: TP=1, FP=0. Справжній gap не виключає
  відому подію з overall recall. Менше 28 діб → block CI=null.
  Для selection alert_end=23.09 23:25, event_start=19.09 00:00,
  event_end=24.09 00:25 за Києвом; обидві праві межі виключні.
  ```python
  assert metrics["tp_alerts"] == 1
  assert metrics["fp_alerts"] == 2
  assert metrics["precision"] == pytest.approx(1 / 3)
  assert metrics["fp_reasons"]["duplicate_unmatched"] == 2
  ```
- [ ] Запустити `python -m pytest tests/research/test_surge_metrics.py tests/research/test_surge_report.py -q`; FAIL.
- [ ] Реалізувати chronological one-to-one matching, загальний recall
  чистих подій і умовний recall доступних подій. Positive known-match
  має пріоритет над unknown іншої частини; unmatched uncertain horizon
  лишається unassessable. Known duplicate без іншої події → FP
  `duplicate_unmatched` лише за повністю відомого горизонту.
  Порядок, tie-break, temporal cohorts, carry-in, CI й stop rule —
  за spec/v1. Усі denominator/exclusion counts експортуються.
  Рахувати перетини unknown з вікнами як множини, не суму дублів.
- [ ] Побудувати CSV/JSON та локальний інтерактивний звіт через чинний
  Data report workflow. Синтетичний preview окремо позначити; дані
  реальних кандидатів підставляти лише після виконаних запусків.
  Перевірити пошук ID, N/A, причини, нульові знаменники, часові межі.
- [ ] Повторити тести; PASS. Commit: `feat: звітувати якість по чергах і невідомих вікнах`.

### Task 8: Перевірений частковий запуск на чотирьох дозволених чергах

**Files:** create `docs/research/shared-surge-2026-10-09/README.md`,
`protocol-v1.json`; локально `dist/shared-surge-experiment/pilot-*`.

**Interfaces:** CLI `validate`, `replay`, `fit`, `compare`, `report`,
`legacy` з обов'язковими `--manifest` та новим `--output`;
`--allow-partial` явно потрібний, якщо відсутні ID.

- [ ] Записати manifest з seed/сіткою/періодами v1 і SHA обох уже
  дозволених gzip із frozen source_hashes. Зберегти manifest до fit.
  Зафіксувати gates Tasks 1–7; без успішного DB parity цей крок чекає.
- [ ] Виконати validate/replay з latency 0 і 60 на ID 1,6,17,29;
  два повтори дають однакові рішення й агрегати. Unsupported frozen
  не викликається навіть при прапорці partial.
- [ ] Запустити незмінний та адаптований legacy evaluator на development
  до 02.10, зіставити semantic JSON після вилучення лише службових шляхів.
  Новий незалежний період не читати для добору; legacy mismatch блокує fit.
- [ ] Виконати fit/compare за manifest, показати решту 34 ID як
  `data_not_available` для calendar/trend/pooled і N/A для frozen;
  Chop-local має N/A для всіх ID, крім 17, незалежно від наявності даних.
  Це pilot, без вибору переможця для всіх 38 і без заяв про 99%.
- [ ] Зберегти лише агрегований receipt, команди і hashes у docs;
  приватні input/feature/alert traces залишити локально. Commit:
  `docs: зафіксувати часткову репетицію дослідницького стенда`.

### Task 9: Конкретний план отримання відсутніх даних

**Files:** create `docs/research/shared-surge-2026-10-09/DATA-PLAN.md`;
локальний перевірений export helper без auto-run.

- [ ] На підставі каталогу аудиту вказати точні 34 відсутні ID,
  період 06.08.2026 —02.10.2026 00:00 Київ exclusive і чотири поля:
  ID, timestamp, count, pause. Очікуваний обсяг із аудиту —2 687 156 рядків;
  свіже агреговане SELECT підтверджує фактичний обсяг перед запитом дозволу.
- [ ] Окремо описати потрібний журнал циклів: timestamp, success boolean,
  duration_ms, лише безпечний reason class. Жодних raw error, токенів,
  персональних даних, підписок або FCM. Обґрунтувати кожне поле.
- [ ] Зазначити конкретний приватний локальний каталог поза Git,
  ACL, hashes, обмежені SELECT, один запит, timeout 15 с, паузи,
  контроль неповного завантаження й запропонований строк зберігання.
  Перевірити helper на synthetic DB без production записів.
- [ ] Запросити окреме явне погодження саме цього готового плану.
  До відповіді продовжувати лише незалежні локальні перевірки.
  Якщо дозволу немає, статус Task 10 — «очікує даних», не «виконано».

### Task 10: Порівняння всіх черг і фіксація наступного випробування

**Files:** update research README, `protocol-v1.json` із фактичними
source hashes до fit; create `RESULTS.md`, `CANDIDATE-FREEZE.json`
лише якщо критерій v1 дозволяє наступний тест; update RELEASE-READINESS.md.

- [ ] Після окремого дозволу виконати Data Plan; звірити hashes,
  count, часові межі, ключі, якість і агрегати з аудитом. Пізній backfill
  оформити новим input version, не переписати попередній receipt.
- [ ] До повного fit зафіксувати manifest та перевірити незмінність
  формул/сітки після pilot. Запустити однакові train/selection/development
  для всіх черг. Зберегти всі trials і обидва latency сценарії.
- [ ] Сформувати 190 рядків, обидва окремі frozen результати, 38-ID
  зрізи подій/+200/недоступності, counts зачеплених unknown-вікон;
  звірити суми й знаменники з trace, перевірити repeatability.
- [ ] Провести один завершальний review методики й реалізації за
  spec/plan; виправити доведені помилки, повторити пов'язані перевірки.
  CI виконати на точному head; усі навчальні результати залишаються локальними.
- [ ] Виконати stop rule: criterion_not_met/insufficient_evidence
  завершують порівняння без приймання і додаткового перебору. Якщо P/R
  дозволяють наступний дослід за v1, записати artifact/policy/source hashes,
  підтримувані ID та наступні 28 повних діб origins від першої київської
  опівночі після freeze. Оцінювання майбутнього потребує фактичних даних
  і окремого дозволу на їх перенесення. Не створювати таймер чи deployment.
- [ ] Зберегти агрегований звіт і readiness з розділеними статусами:
  код, CI, дослід; production/Android/телефон/Play — не виконувались.
  Commit: `docs: підсумувати спільний експеримент по всіх чергах`.

## Команди перевірки перед завершенням

```sh
python -m pytest tests/research -q
python -m pytest -c services/backend/pytest.ini services/backend/tests/unit -q
bash scripts/test_database.sh surge
python scripts/verify_ci_scopes.py
python scripts/verify_core_provenance.py
python scripts/verify_android.py
git diff --check
```

Новий research workflow має перевіряти окремий пакет і залежності,
а зміна database suite — відповідні інтеграційні gates. Відсутній або
пропущений CI не означає успіх. Повний локальний набір не запускається
для самого документа; наведені команди — gates майбутньої реалізації.

## Самоперевірка плану та handoff

- Spec §§1–4 → Tasks 1,4,9; §§5–6 → Tasks 2–5; §7 → Tasks 3,6,8,10;
  §8 → Task 7; §9 → Tasks 1,8–9; §10 → Tasks 5,7–10.
- Межі дозволів виділені; дані 34 ID не завантажені, код ще не написаний.
- Спосіб виконання: самим агентом у поточній сесії, як раніше обрав власник.
- Наступна дія — review цього записаного плану власником. Лише після
  погодження починається Task 1; новий export і deployment ним не дозволяються.
