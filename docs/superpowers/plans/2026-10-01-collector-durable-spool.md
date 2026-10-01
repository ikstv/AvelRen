# Стійка черга collector — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Зберігати кожен отриманий цикл collector під час тимчасової недоступності PostgreSQL і безпечно дозаписувати його після відновлення БД.

**Architecture:** Один producer раз на 60 секунд фіксує цикл у локальному SQLite WAL; один DB writer переносить `pending` у PostgreSQL FIFO та підтверджує їх лише після звіреного commit. `capture-only` вимикає DB writer без зупинки producer і переживає restart контейнера.

**Tech Stack:** Python 3.14, stdlib `sqlite3`, asyncio, psycopg 3, PostgreSQL/TimescaleDB, Docker Compose, pytest.

**Spec:** [2026-10-01-collector-durable-spool-design.md](../specs/2026-10-01-collector-durable-spool-design.md)

Статус: очікує перегляду власником; цей план не дозволяє реалізацію чи production-операції.

## Global Constraints

- Тільки один `collector`; рівно один upstream-запит за цикл, початки циклів через 60 секунд, без catch-up і паралельних запитів.
- Не змінювати Device ID, endpoint v5 `/workload/1`, заголовки, truck-only scope чи політику `429`/`5xx`/timeout.
- Локально зберігати лише нормалізовані поля відповіді й метадані циклу; без DSN, Device ID, секретів, заголовків і сирого body.
- SQLite: `journal_mode=WAL`, `synchronous=FULL`, файли `0600`, каталог `0700`, UID 10001, межа 1 GiB; перед maintenance — 2 GiB вільно й запас квоти понад подвійний виміряний обсяг погодженого вікна.
- Цикли старші за 120 секунд при replay не породжують push/ETA; причина пропуску зберігається в `collector_runs.derived_error`.
- Ніяких запитів до єЧерги в тестах; Docker-тести використовують лише одноразові ресурси й синтетичні відповіді.
- Не змінювати вже застосовані міграції; production deployment, БД, ролі й контейнери потребують окремого явного GO.

## File Structure

- `services/backend/src/avelren/collector_spool.py` — формат v1, SQLite-транзакції, recovery, integrity, capacity, status і режим.
- `services/backend/src/avelren/collector_replay.py` — FIFO DB writer, звірка конфліктів, derived-політика й backoff без upstream-запитів.
- `services/backend/src/avelren/collector.py` — producer/scheduler і запуск двох незалежних задач; DB gate лишається в writer.
- `services/backend/src/avelren/collector_control.py` — локальна operator-only команда `capture-only on|off|status` і підтвердження переходу.
- `services/backend/tests/unit/test_collector_spool.py`, `test_collector_replay.py`, оновлений `test_collector_cycle.py`, `test_collector_control.py` — швидкі тестові контракти без мережі.
- `services/backend/tests/database/test_collector_spool.py` — replay проти одноразової TimescaleDB з чинними ролями/міграціями.
- `services/backend/Dockerfile`, `docker-compose.yml`, `ops/compose-production-contract-test.sh` — постійний том і перевірка mount/UID; `ops/COLLECTOR-SPOOL.md` — експлуатація та recovery.
- `ops/collector-spool-integration-test.sh`, `ops/compose.collector-spool-test.yml` — окремий Docker-проєкт із синтетичним upstream, test DB і disposable spool volume; без прискорення production scheduler.
- `docs/RELEASE-READINESS.md` і `.github/workflows/database.yml` — окремий запис про deployment/приймання та відповідні CI-перевірки.

## Review Focus

1. Стрибок системного часу назад: `time` уже зайнятий іншим payload; тест у Task 2 має лишити цикл `pending`, а не мовчки поглинути його через `ON CONFLICT DO NOTHING`.
2. `429`, timeout і порожня відповідь: тест у Task 1/3 має зберегти помилковий цикл без спостережень і без повторного upstream-запиту.
3. Crash після `started`, але до durable payload: тест у Task 1/2 має записати `interrupted_before_durable_result`, не вигадуючи спостережень.
4. Копія лише `.sqlite3` без WAL: Task 4 має заборонити таку recovery-процедуру й перевірити online backup/integrity.
5. Давні цикли після довгого outage: Task 2/4 має довести відсутність застарілого push і явний `derived_error`.

---

### Task 1: SQLite-журнал циклів

**Files:** Create `services/backend/src/avelren/collector_spool.py`; test `services/backend/tests/unit/test_collector_spool.py`.

**Interfaces:** `CapturedCycle(seq: int, at: datetime, http_status: int | None, duration_ms: int, body_sha256: str | None, error: str | None, countries: tuple[Country, ...], items: tuple[WorkloadItem, ...])`; `SpoolStore(path: Path, max_bytes: int = 1_073_741_824)` with `begin(at: datetime) -> int`, `finish(seq: int, result: FetchResult, vehicle_type: int) -> None`, `recover_started() -> None`, `next_pending() -> CapturedCycle | None`, `ack(seq: int) -> None`, `prune_acked(now: datetime) -> None`, `set_capture_only(enabled: bool) -> None`, `capture_only() -> bool`, `set_mode_ack(enabled: bool) -> None`, `record_replay_error(message: str | None) -> None`, `status() -> SpoolStatus`, `maintenance_preflight(window_minutes: int) -> SpoolStatus`, `backup_to(path: Path) -> None`. `SpoolStatus` exposes `pending_count`, `oldest_pending_at`, `capture_only`, `mode_ack: bool | None`, `last_error`, `max_cycle_bytes`. A mode request resets ack to `None`; the daemon sets it to the requested value after transition. The DB writer and operator CLI consume these methods; no other module writes SQLite directly.

- [ ] **Step 1: Write failing unit tests** named `test_pending_survives_restart` (`next_pending().seq == seq`), `test_source_error_is_pending` (error retained, `items == ()`), `test_started_recovers_as_interrupted` (exact error `interrupted_before_durable_result`), `test_payload_rejects_corruption_or_unknown_version`, `test_capture_mode_requires_new_ack`, `test_acked_prunes_after_24_hours`, `test_maintenance_preflight_rejects_low_space_or_quota` and `test_spool_permissions_and_no_secrets`. Include the 1 GiB/2 GiB boundaries and normal truck-only normalized payload assertions.
- [ ] **Step 2: Run red tests:** `python -m pytest -c services/backend/pytest.ini services/backend/tests/unit/test_collector_spool.py -q`; expect missing `collector_spool` interfaces.
- [ ] **Step 3: Implement the listed interfaces** using SQLite transactions, WAL/FULL, canonical JSON plus SHA-256, `sqlite3.Connection.backup()` and explicit schema version 1. Check db+wal+shm size and filesystem free bytes before accepting maintenance; on corruption/quota failure preserve existing rows and raise a typed `SpoolUnavailable`.
- [ ] **Step 4: Run green tests:** same command; expect 0 failures. Run `python -m ruff check services/backend/src/avelren/collector_spool.py services/backend/tests/unit/test_collector_spool.py`.
- [ ] **Step 5: Commit** only Task 1 files with Ukrainian message `feat: додати стійкий SQLite-журнал циклів`.

### Task 2: Один FIFO writer до PostgreSQL

**Files:** Create `services/backend/src/avelren/collector_replay.py`; modify `services/backend/src/avelren/db.py` only for read-back verification; test `services/backend/tests/unit/test_collector_replay.py` and `services/backend/tests/database/test_collector_spool.py`.

**Interfaces:** consumes `SpoolStore.next_pending()/ack()` and `CapturedCycle` from Task 1; produces `async def replay_once(store: SpoolStore, pool: AsyncConnectionPool, now: datetime) -> bool` (`False` only when queue empty or capture-only) and `async def replay_loop(store: SpoolStore, pool: AsyncConnectionPool, stop: asyncio.Event) -> None`. `verify_committed_cycle(conn: AsyncConnection, cycle: CapturedCycle) -> None` compares journal fields and every observation against payload, raising `ReplayConflict` on mismatch. No function in this module calls `fetch_workload`.

- [ ] **Step 1: Write failing tests** named `test_replay_commits_fifo` (original timestamps/order), `test_db_outage_retains_pending`, `test_commit_before_ack_is_idempotent` (one `collector_runs` plus exact observations after replay twice), `test_time_collision_retains_pending` (`ReplayConflict`), `test_interrupted_cycle_records_error_only`, `test_old_cycle_skips_push` (`derived_error` set after 121 s) and `test_fresh_cycle_runs_derived` (age 120 s). Use an isolated DB fixture to assert actual rows under `avelren_collector`; assert fake upstream call count stays zero in writer tests.
- [ ] **Step 2: Run red unit and DB tests:** `python -m pytest -c services/backend/pytest.ini services/backend/tests/unit/test_collector_replay.py -q` and `bash scripts/test_database.sh`; expect Task 2 cases to fail for absent interfaces.
- [ ] **Step 3: Implement** `replay_once`, `replay_loop` and `verify_committed_cycle` with one primary PostgreSQL transaction per cycle, original `at`, bounded DB-only backoff and full read-back before `ack`. Keep derived work in a separate transaction; if age >120 s, call `record_derived` with explicit delayed-replay reason and no alert evaluation.
- [ ] **Step 4: Run green unit, DB and ruff:** the Step 2 commands and `python -m ruff check services/backend/src/avelren/collector_replay.py services/backend/src/avelren/db.py services/backend/tests/unit/test_collector_replay.py services/backend/tests/database/test_collector_spool.py`; expect 0 failures.
- [ ] **Step 5: Commit** Task 2 files with `feat: дозаписувати цикли в БД без дублікатів`.

### Task 3: Producer, startup і capture-only

**Files:** Modify `services/backend/src/avelren/collector.py`, `services/backend/tests/unit/test_collector_cycle.py`; create `services/backend/src/avelren/collector_control.py`, `services/backend/tests/unit/test_collector_control.py`.

**Interfaces:** `async def run_cycle(client: httpx.AsyncClient, store: SpoolStore) -> None` uses `begin` before exactly one fetch and `finish` before any DB work. `collector_control.main(argv: Sequence[str] | None = None) -> int` accepts only `capture-only on|off|status`, uses the fixed collector spool path, writes no secrets and waits up to 30 s for `mode_ack` from the running producer/writer. Task 2 owns replay; this task only schedules it and acknowledges mode after closing its DB pool.

- [ ] **Step 1: Write failing fake-clock tests** named `test_start_times_remain_60_seconds_apart` (three starts at 0/60/120 despite replay), `test_one_fetch_per_cycle_when_db_down`, `test_startup_without_db_still_captures`, `test_capture_only_survives_restart`, `test_control_acks_only_after_pool_close` and `test_control_times_out_after_30_seconds`. Assert no real HTTP transport is used.
- [ ] **Step 2: Run red tests:** `python -m pytest -c services/backend/pytest.ini services/backend/tests/unit/test_collector_cycle.py services/backend/tests/unit/test_collector_control.py -q`; expect new behavior to fail.
- [ ] **Step 3: Implement** spool-first producer and independent DB writer in `collector.main()`. Validate source config before fetch, open/verify SQLite before any DB operation, move schema gate to writer, read durable capture-only mode each cycle, stop/restart writer without stopping producer; no new public endpoint or external dependency.
- [ ] **Step 4: Run green unit suite and ruff:** `python -m pytest -c services/backend/pytest.ini services/backend/tests/unit -q` and `python -m ruff check services/backend/src services/backend/tests`; expect 0 failures.
- [ ] **Step 5: Commit** Task 3 files with `feat: збирати цикли під час недоступності БД`.

### Task 4: Постійний том, recovery й наскрізне приймання

**Files:** Modify `services/backend/Dockerfile`, `docker-compose.yml`, `ops/compose-production-contract-test.sh`, `.github/workflows/database.yml`, `docs/RELEASE-READINESS.md`; create `ops/COLLECTOR-SPOOL.md`, `ops/collector-spool-integration-test.sh`, `ops/compose.collector-spool-test.yml`; extend `services/backend/tests/database/test_collector_spool.py` and the unit tests from Tasks 1–3.

**Interfaces:** fixed container path `/var/lib/avelren/collector-spool/cycles.sqlite3`, dedicated named volume `collector_spool` mounted only into `collector`; operator runs `python -m avelren.collector_control capture-only on|off|status` inside that container. `ops/COLLECTOR-SPOOL.md` defines free-space/integrity/mode-ack gates and Online Backup API copy; no command in this task executes on production.

- [ ] **Step 1: Write failing Compose contract and Docker integration tests** named `test_collector_spool_volume_is_private_and_persistent` (only collector mount, not tmpfs, UID 10001 creates `0600` file) and `test_spool_outage_restart_and_replay` (five explicitly invoked fake-upstream cycles during DB outage, fresh process using same disposable volume, FIFO DB rows and zero stale pushes). Add `test_corrupt_or_full_spool_blocks_maintenance` and `test_online_backup_keeps_pending_wal_rows`; a DB-file-only copy must fail a count/digest comparison. The harness invokes cycles directly and does not shorten the production 60-second scheduler.
- [ ] **Step 2: Run red checks:** `bash ops/compose-production-contract-test.sh`, `bash scripts/test_database.sh`, `bash ops/collector-spool-integration-test.sh` and `python -m pytest -c services/backend/pytest.ini services/backend/tests/unit -q`; expect newly added cases to fail.
- [ ] **Step 3: Add runtime mount, image directory ownership, tests, CI commands and Ukrainian runbook.** Record code/CI/deployment/staging/phone as separate states in `docs/RELEASE-READINESS.md`. Document image rollback only with `pending=0` or compatible spool schema, and require separate GO before any server-side rehearsal or adoption.
- [ ] **Step 4: Run green checks:** Step 2 commands, `python -m ruff check services/backend/src services/backend/tests` and `git diff --check`; expect 0 failures. In CI, verify exact-commit `database`, backend-core and repository checks; do not infer success from absent checks.
- [ ] **Step 5: Commit** Task 4 files with `ops: перевірити постійний том і відновлення черги`.

## Handoff

Після чотирьох комітів — окремий whole-branch review, PR і перевірка
CI на точному head. Не зливати й не розгортати код лише за результатом
unit-тестів. Перед будь-яким production rollout окремо погодити конкретні
команди, recovery/rollback, спостереження `pending=0` і перевірку 60-секундного
ритму. Потім окремо повернутися до дизайну переходу прав PostgreSQL.
