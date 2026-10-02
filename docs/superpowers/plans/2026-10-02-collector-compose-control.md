# План реалізації Compose-керування collector

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Штатно керувати встановленим spool-collector через окремий Compose зі збереженням черги й перевіркою єдиного poller.

**Architecture:** Collector-only project використовує існуючі зовнішні network/volume та перевірений immutable image. Shell control серіалізує операції, Python preflight звіряє фактичну топологію. Restore отримує guard до мутацій; переходи прав БД лишаються окремим етапом.

**Tech Stack:** Docker Compose, Bash, flock, Python stdlib/unittest, чинний SQLite SpoolStore, PostgreSQL/TimescaleDB; додаткових runtime Python-залежностей немає.

**Spec:** [Схвалена специфікація](../specs/2026-10-02-collector-compose-control-design.md), коміт `855d5ec`, review власника — «так».

## Глобальні обмеження

- Project `avelren-collector-runtime`, service `collector`, container `avelren-collector-1`.
- External network `avelren_default`, external volume `avelren_collector_spool_v1`; spool mount `/var/lib/avelren/collector-spool`.
- Поточний image ID `sha256:1ab8437b7e789ec44a6971604bd56d9c43a1117c04278cb5faf550ca7d3235a1`, embedded SHA `0c62f543643b74a177ee56e5351cf518c1b9053d` повторно перевіряються перед production.
- Root-owned приватні manifest/env/state поза checkout; env 0600; без виводу env/DSN.
- UID/GID 10001, cap_drop ALL, no-new-privileges, read-only root, tmpfs /tmp 64 MiB, pids_limit 128, restart unless-stopped. Нових CPU/memory ceilings немає.
- Не змінювати єЧерга wire contract, Device ID, DSN, applied migrations чи ролі. Один poller, пауза щонайменше 60 секунд між stop/start.
- Немає build/pull/latest, db/migrate залежностей, `down -v`, `--remove-orphans`, reconciliation інших служб.
- Тести використовують синтетичний HTTP та власні ресурси, без доступу до єЧерги/production.
- Production-запис лише після окремого конкретного GO, перевірок і командного відкату.
- Виконання: збережено вибір власника «виконуй сам у цій сесії». Review цього записаного плану ще потрібен перед реалізацією.

## На чому зосередити review

1. Env з `$`, пробілами чи лапками має передаватися буквально, без shell eval та секретів у помилках — тест завдання 1.
2. Другий poller з довільним ім'ям або невідомий контейнер на canonical name має блокувати старт — тест завдання 2.
3. Signal після stop, одночасні оператори та збій годинника не повинні обходити паузу/lock — тест завдання 3.
4. Непорожня черга та збережений capture-only мають переживати заміну й відкат — реальна репетиція завдання 5.
5. Недоступний Docker або несумісний restore target мають відхиляти restore до будь-якої мутації — тест завдання 4.

## Карта файлів

- `ops/compose.collector-runtime.yml`: одна runtime-служба.
- `ops/collector-runtime-preflight.py`: приватний manifest, effective config, Docker inventory; безпечний JSON verdict.
- `ops/collector-runtime-control.sh`: CLI, lock, state і керовані Docker/Compose операції.
- `ops/collector-runtime-contract-test.py`: реальний Compose config та фіктивний Docker для негативних випадків.
- `ops/collector-runtime-control-contract-test.sh`: операційний trace, сигнали та lock.
- `ops/restore-production.sh`, `ops/restore-production-contract-test.sh`: ранній guard топології та його порядок.
- `ops/collector-runtime-integration-test.sh`, `ops/collector-runtime-daemon-test.py`: ізольоване перемикання/відкат.
- `ops/COLLECTOR-RUNTIME.md`, `ops/COLLECTOR-SPOOL.md`: runbook, сумісність legacy та maintenance.
- `.github/workflows/database.yml`, `scripts/verify_ci_scopes.py`: запуск усіх нових перевірок і контроль фільтрів.
- `docs/RELEASE-READINESS.md`: окремі фактичні етапи готовності.

## Завдання 1: Compose-контракт і приватний manifest

**Interfaces:** manifest JSON має поля `source_commit`, `image_id`, `env_file`,
`compose_file`, `project`, `container_name`, `network`, `volume`, `state_dir`.
Production paths абсолютні, root-owned, без symlink чи group/world write.
Compose отримує `COLLECTOR_IMAGE_ID`, `COLLECTOR_ENV_FILE`,
`COLLECTOR_CONTAINER_NAME`, `COLLECTOR_NETWORK`, `COLLECTOR_VOLUME` з валідованого
manifest; shell не source-ить JSON/env. Для production застосовуються сталі
імена глобального контракту. У тестовому режимі дозволені лише власні
ресурси з префіксом `avelren-runtime-test-`; production імена заборонені.

- [ ] Написати RED-тести `test_single_service_external_resources`, `test_security_matches_live`, `test_missing_manifest_field_denied`, `test_private_file_permissions_denied`, `test_env_values_are_literal`. Assertions: тільки `collector`; відсутні build/depends_on/ports; external=true; UID=10001:10001; усі security параметри з глобального контракту; sentinel env відсутній у stdout/stderr і не виконується як команда.
- [ ] Запустити `python3 ops/collector-runtime-contract-test.py`; зафіксувати FAIL через відсутні файли/інтерфейс, без старту контейнерів.
- [ ] Створити Compose і Python функцію `load_manifest(path: Path, *, test_mode: bool = False) -> dict`. Встановити `env_file` format `raw`, щоб Compose не інтерполював `$`; preflight перевіряє підтримку цього формату фактичним Compose config й відмовляється при несумісній версії. Приватний файл формувати з Docker Env як literal key=value, відхиляти newline/NUL.
- [ ] Повторити контракт із реальним `docker compose ... config --format json`. Python тримає config/environment лише в пам'яті; друкує allowlist metadata. Очікується PASS для всіх assertions, жодних daemon мутацій.
- [ ] `git diff --check`, commit «Додати окремий Compose-контракт collector» з трьома новими файлами цього завдання.

## Завдання 2: Фактичний preflight і статус

**Interfaces:** `validate_runtime(manifest: dict, effective: dict, inventory: list[dict], *, require_managed: bool) -> list[str]` повертає безпечні категорії порушень.
CLI `python3 ops/collector-runtime-preflight.py --manifest PATH --phase config|status|managed`:
exit 0 — перевірено; nonzero — відмова, без dump конфігурації. `config`
допускає поточний standalone як відомий migration target, але не дозволяє
control-мутації; `managed` вимагає правильні Compose labels.

- [ ] Додати RED `test_foreign_canonical_container_denied`, `test_second_poller_custom_name_denied`, `test_wrong_image_volume_network_denied`, `test_stopped_legacy_preserved`, `test_missing_external_resource_denied`, `test_image_source_sha_mismatch`. Assert nonzero до будь-якого create/start; legacy stopped не видаляється; Compose project/service і module command враховані в inventory.
- [ ] Запустити `python3 ops/collector-runtime-contract-test.py`, підтвердити нові FAIL.
- [ ] Реалізувати `validate_runtime` і CLI з Docker subprocess argv, без shell. Звіряти Image ID, безпечний embedded SHA, command, mounts, networks, labels та hardening. Неповний/помилковий inspect дає відмову. Перед початковим запуском перевірити image через offline `network none` probe без source polling; цей probe класифікувати як окрему production-операцію в майбутньому GO.
- [ ] Додати статус spool через `docker exec` без TTY і чинний `SpoolStore.status()`: captured/acked/pending/oldest_pending, capture_only/mode_ack/last_error. Статус stopped контейнера не запускає контейнер для читання. Передбачити безпечне повідомлення «spool недоступний» з nonzero при помилці.
- [ ] Повторити контракт, `python3 -m py_compile ops/collector-runtime-preflight.py`, commit «Перевіряти фактичний collector перед керуванням».

## Завдання 3: Керовані команди, lock і пауза

**Interfaces:** `bash ops/collector-runtime-control.sh --manifest PATH COMMAND [ARGS]`.
COMMAND: `preflight`, `status`, `logs`, `start`, `stop`, `restart`,
`capture-only status|on|off`. Lock/state розташовані у перевіреному state_dir.
`preflight --window-minutes N` викликає `maintenance_preflight(N)`; N — додатне
ціле число. `logs` — явний operator запит на журнали, без env/config dump.

- [ ] Написати RED shell trace cases: `second-poller`, `unmanaged-target`, `concurrent-lock`, `stop-start-delay`, `restart-delay`, `signal-after-stop`, `backward-clock`, `missing-state`, `capture-timeout`, `capture-ack`, `no-other-service-mutation`. Фіктивний Docker містить sentinel DSN; assertions: DSN відсутній у виході, лише collector control, пауза >=60, nonzero timeout, signal не запускає fallback.
- [ ] `bash ops/collector-runtime-control-contract-test.sh` має FAIL на відсутньому wrapper.
- [ ] Реалізувати CLI з `set -euo pipefail`, `flock` для всіх мутацій і read-only preflight під lock. Перевірити наявність flock на production до встановлення; автоматично пакети не встановлювати. `start`/`restart` використовують явний file/project та `--no-deps --no-build --pull never`; не роблять загального stack up.
- [ ] Graceful stop: зафіксувати підтверджений stopped state та час атомарним state-file (0600). Для restart не використовувати Compose restart: явні stop, пауза, start. Пауза поточної операції за monotonic clock; відсутній/застарілий/майбутній timestamp означає повні 60 секунд. Після startup повторити managed preflight. State не видаляти trap-ом; невдала перевірка не запускає legacy.
- [ ] Capture-only викликає чинний `python -m avelren.collector_control capture-only ...`; зберегти nonzero та timeout 30 секунд. `on/off` вважаються успішними тільки після mode acknowledgement; не міняти request самостійним SQLite update.
- [ ] `bash -n ops/collector-runtime-control.sh ops/collector-runtime-control-contract-test.sh`, обидва contracts PASS; commit «Додати безпечні операторські команди collector».

## Завдання 4: Restore guard і maintenance runbook

**Interfaces:** `avelren_require_supported_collector_topology()` у
`ops/restore-production.sh`: read-only Docker inventory; legacy Compose
collector підтриманий за чинним контрактом; standalone/окремий project,
відсутній Docker чи неоднозначний стан відхиляються. Виклик після operator
identity check, до capture artifact/snapshot/maintenance.

- [ ] Додати RED `unsupported-collector-topology`, `docker-unavailable`, `legacy-topology` у restore contract. Trace assertions: у перших двох немає snapshot/maintenance/stop/engine/start; legacy зберігає чинну послідовність; stdout/stderr не містять sentinel.
- [ ] Запустити `bash ops/restore-production-contract-test.sh`, підтвердити нові FAIL.
- [ ] Додати guard та виклик до мутацій. Не змінювати restore engine, applied SQL або snapshot/spool reconciliation.
- [ ] Створити `ops/COLLECTOR-RUNTIME.md`: manifest contract, CLI, окреме початкове перемикання і відкат, неможливість додати labels без recreate; зберегти джерело `/opt/avelren/deploy/postgres-adopt.sh` та посилання на #74/#75/#76. Написати явно: legacy adoption поки несумісний, root може обійти wrapper, старий Compose collector заборонений.
- [ ] Оновити `ops/COLLECTOR-SPOOL.md`: preflight + Online Backup поза томом, capture-only on і ack до робіт БД, off/schema ack/replay після них; backup БД при pending не повний. Повний restore відокремити від maintenance.
- [ ] Пройти restore-production, preflight та identity contracts; `git diff --check`; commit «Захистити restore від несумісної collector-топології».

## Завдання 5: Реальна репетиція перемикання й відкату

**Interfaces:** `bash ops/collector-runtime-integration-test.sh` створює
унікальні `avelren-runtime-test-*` project/network/volume/container, очищає
тільки власні ресурси. Driver Python має CLI `seed`, `run`, `verify`,
`backup`, `wait-empty`; використовує синтетичний transport зі зразка
`ops/collector-spool-daemon-test.py`, без зміни production collector.

- [ ] Написати RED репетицію з assert для migration labels, одного poller, незмінних synthetic Device ID/env/image/volume, payload digests та capture-only. Запустити; очікуваний FAIL на відсутньому integration driver, не на реальному API.
- [ ] Реалізувати harness: власна БД із чинними штатними bootstrap/migrations, internal network, реальний daemon; кандидата зібрати лише локально для тесту. Init external spool UID10001 у власному томі. Для literal env/security/lock контрактів використовувати Linux із flock; на Windows запускати цей harness у власному Linux тестовому контейнері, не імітувати flock як доказ взаємного виключення.
- [ ] БД недоступна: отримати щонайменше два pending природних цикли; увімкнути й підтвердити capture-only. Зробити Online Backup й integrity/digest check. Graceful stop standalone, зберегти stopped контейнер; почекати 60 секунд, створити Compose collector з того самого image/volume. Перевірити persistent mode, єдиний poller і pending.
- [ ] Повернути тільки тестову БД, capture-only off; assert FIFO, pending=0, без дублів/запізнілих derived push. Виконати керований restart з trace timestamps; повторно перевірити interval >=60 між handoffs та runtime security.
- [ ] Зупинити Compose, перевірити Online Backup; повернути збережений сумісний standalone після 60 секунд. Assert volume/image незмінні, новий природний цикл, no dual poller. Cleanup тільки ресурсів цієї репетиції; зберегти безпечний evidence JSON (SHA коду, image ID, timestamps, cycle count, pending/digests, результат rollback).
- [ ] Повторити репетицію до PASS без додаткового polling; commit «Перевірити Compose-перемикання та відкат collector».

## Завдання 6: CI, review і готовність до окремого GO

- [ ] У `scripts/verify_ci_scopes.py` додати regression cases для нових ops-файлів: database workflow обов'язково запускається на PR і main push. Додати assertions на наявність contract/integration команд у `.github/workflows/database.yml`; RED — ці кроки ще відсутні.
- [ ] У database workflow додати bash syntax, Python compile/contracts, control contract під Linux із root-owned fixture і інтеграційну репетицію; використовувати чинні pinned actions. Виміряти сумарний runtime; змінити timeout тільки якщо доказ часу репетицій вимагає цього. Не прибирати старі DB/restore/spool перевірки.
- [ ] Запустити `python3 scripts/verify_ci_scopes.py`, `python3 scripts/verify_core_provenance.py`, залежні contracts, `bash scripts/test_database.sh` та нову integration репетицію. Перевірити чинний spool contract у складі DB набору; якщо він там відсутній, запустити явно. На Windows використовувати повний Git Bash/Python paths і Linux Docker для операцій, які залежать від flock/UID.
- [ ] Оновити release registry фактичними source/local evidence; CI/production/Android/телефон/Play не позначати без доказів. `git diff --check`, commit «Підключити перевірки Compose-керування collector до CI».
- [ ] Виконати whole-branch review за навичкою executing-plans/requesting-code-review після реалізації, виправити конкретні findings та повторити зачеплені перевірки. Не переписувати опубліковану історію.
- [ ] Створити PR з точним переліком змін, походженням, local evidence та обмеженнями; прикріпити його до чату. Дочекатися всіх залежних CI checks точного фінального head; docs/source/CI не дорівнюють server deployment.
- [ ] Підготувати майбутній командний production-план: свіжа read-only інвентаризація й effective config; приватний manifest/env; перевірені DB/SQLite backup; offline probe; stop/rename/create/start з паузою; п'ять природних циклів; незмінність інших служб; відкат до сумісного збереженого spool-контейнера. Власнику показати точні записи, контрольні суми й відкат та запросити окремий GO. До GO нічого на сервері не встановлювати.

## Самоперевірка плану

Spec coverage: Compose/security/resources — 1; inventory/status — 2;
lock/control/60 секунд/mode ack — 3; maintenance та restore boundary — 4;
pending/backup/rollback/isolation — 5; provenance/CI/release/production GO — 6.
Усі п'ять review conditions мають конкретні tests у відповідних завданнях.
Legacy DB-role orchestrator не оголошується адаптованим; source restore guard
не оголошується встановленим. Автоматичні OS updates/reboot не додаються.
