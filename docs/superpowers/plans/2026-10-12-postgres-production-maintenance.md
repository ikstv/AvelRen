# PostgreSQL production maintenance — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Реалізувати maintenance adapter та операторський CLI для ownership/ACL adoption і явного inverse зі збереженням фактичних служб, timers/jobs, конфігурації та collector spool.

**Architecture:** Python adapter реалізує чинний RuntimeVerifier; orchestrator керує maintenance до приймання restart. Host lease серіалізує весь stop/SQL/start сценарій, наявний DB lifecycle guard — SQL та receipts. CLI створює тільки concrete adapters; injections доступні лише програмному isolated harness.

**Tech Stack:** Python/psycopg, PostgreSQL16/TimescaleDB2.30.1, Linux root/TTY, Docker Compose5.5.1, systemd, pytest, existing private evidence I/O.

**Spec:** [Погоджена специфікація](../specs/2026-10-11-postgres-production-adoption-design.md), етап2. DSN cutover — окремий етап3.

База: main eed0cb0f5a337e88467943017bbca3a04d2593e2, [PR121](https://github.com/ikstv/AvelRen-ORIGINAL/pull/121). Усі8 checks PR і relevant main workflows SUCCESS. Датований аудит11.10 описує mixed images, dirty checkout і legacy collector/watchdog; це орієнтир, не актуальний deployment preflight.

Статус12.10: план для перегляду власником, не реалізація і не дозвіл на серверну операцію. Збережений спосіб виконання: окремий агент і fresh review кожної задачі, потім whole-branch review.

## Global Constraints

Точні вимоги погодженої специфікації:

- «Підготовка коду не дозволяє операцій на сервері.»
- «Застосовані міграції 001–016, дані, функції, паролі й адміністративні ролі не змінюються.»
- «Existing snapshot/plan format 1 і disposable CLI лишаються сумісними.»
- «Секретні env/DSN не копіюються в manifest; для них зберігаємо лише приватну rollback-конфігурацію без логування значень.»
- «Ingress Caddy закривається до зупинки API.»
- «Не видаляємо контейнери чи volumes.»
- «Collector spool не відкриваємо для запису, не очищуємо й не підміняємо; identity шляху/volume має лишитися незмінною.»
- «Adapter призупиняє тільки явно погоджені jobs через штатний Timescale API, зберігає їхній попередній стан і відновлює тільки власні підтверджені зміни.»
- «Не застосовуємо pg_terminate_backend.»
- Production CLI: Linux, root, локальний /dev/tty; ADOPT/INVERSE з повними target і plan digests; inverse має нове підтвердження. DSN/confirmation не в argv, --force/--yes відсутні.
- Restart: повний ordered Compose/override набір, явні services і --no-deps, без pull/build/migrate. Collector: незмінний Device ID, один цикл60s, збереження кожного циклу; tests не звертаються до єЧерги.
- DB коди0 adopted/already_target,1 refused/rolled_back,2 unavailable/invalid,3 rollback_failed,4 commit_unknown; runtime_failed5 зі збереженим DB status.
- «Старі репозиторії зберігаються до повного фінального приймання міграції.»

Фіксований DB lifecycle guard потребує CONNECT до postgres і control/database identity. Quiescence не послаблюємо: active autovacuum, idle clients, prepared transactions і невідомі workers відхиляються. Fixture autovacuum=off не стає production зміною. Evidence0700/files0600 поза verified checkout roots, no symlink/hardlink/overwrite, exclusive publication+fsync.

## Review Focus

1. Physical clone з однаковим system_identifier: actual host/container/runtime mismatch відхиляється (Task1).
2. Два operators/різні evidence paths, lost process після partial stop: спільна host lease і unfinished-state blocker (Task2/4).
3. Timer/job був вимкнений або змінився сторонньо: не ввімкнути й не перезаписати чужий стан (Task2/3).
4. Accepted DB + env/image/override drift перед restart: runtime_failed, ingress closed, DB outcome збережено (Task4).
5. HUP/INT/TERM між COMMIT і receipt чи під час restart: не повторювати SQL і не запускати automatic inverse/restart (Task4/5).

## Конкретні рішення плану

Підтримувана topology описується явним operator manifest: main application із Caddy/API/notifier/watchdog/surge_worker/DB і рівно один collector, у main або перевіреному standalone stack. Unknown stack/client/timer/config означає відмову. Стан enabled/stopped services дозволено зберігати; спочатку stopped не запускати.

Runtime digest містить стабільні identities/configuration. Поточні running/stopped states перевіряються окремо за phase, інакше наша зупинка зламає власний digest. Clean executor source candidate перевіряється окремо від dirty legacy checkout; фактичні старі images не замінюються новим application image.

Ordered Compose paths/hashes можуть бути public лише за відсутності inline secrets. Env snapshots і byte-comparison приватні; public evidence не містить env hashes/секретів/subprocess stderr. Непідтримуваний YAML із secrets відхиляється.

Host lease від baseline до runtime acceptance: root-owned fixed lock directory, ключ host+cluster_identifier+DB_OID, незалежний від operation/evidence paths. Це інший lock ніж DB lifecycle guard; повторне захоплення одного DB ключа не потрібне. Lost lease/boot/config drift анулюють context.

Durable baseline/intent записується перед першою зміною; кожна зміна має intent і actual observation. Невідомий pause/stop результат не повторюється автоматично. Existing containers відновлюються повним Compose набором up -d --no-deps --no-build --pull never --no-recreate з явними clients. Actual flags довести на5.5.1. Missing container/recreate/image drift відхиляються. Ingress останній.

Фонові записи очікуємо в bounded timeout, не terminate/disable autovacuum. Chunk drift вимагає нового плану/підтвердження. Немає generic resume command: unfinished apply блокує новий apply. Explicit inverse можливий лише з proven committed receipts, початковим maintenance baseline і fresh lease/context/confirmation. Unknown потребує окремої read-only діагностики.

Runtime acceptance: API local health/read, DB session identity та негативні probes за чинними ролями; collector природний новий цикл60s зі збереженим Device ID/spool; watchdog/notifier/worker локальні readiness без додаткового push або upstream запиту. Відсутній доказ — runtime unverified, не success.

## Типи та файли

Імпортувати existing MaintenanceContext/RuntimeVerifier, Confirmation, TargetBinding, AdoptionPlan, OperationManifest та AdoptionResult, не дублювати DB executor/evidence formats.

- adoption_runtime.py: frozen RuntimeManifest(payload: dict[str, object]); strict canonical format1 schema; RuntimeHost protocol і LinuxRuntimeHost.
- adoption_maintenance_state.py: MaintenanceLease.assert_owned() -> None; frozen MaintenanceBaseline(runtime: RuntimeManifest, running_ids: tuple[str, ...], timer_states: dict[str, tuple[str, str]]); private numbered phase events.
- adoption_maintenance_clients.py: host/container/timer actions та actual observations.
- adoption_maintenance_jobs.py: frozen JobState(job_id: int, owner: str, scheduled: bool, definition: str), JobChange(before: JobState, paused: JobState). Definition — canonical procedure/config/schedule; mutable statistics окремо.
- adoption_maintenance.py: actual VerifiedRuntime та frozen MaintenanceOutcome(db_status: str | None, runtime_status: str, category: str | None, exit_code: int).
- adoption_maintenance_cli.py: concrete composition root, sanitized JSON/exit mapping.

RuntimeHost.read(kind: str, identity: str) -> dict[str, object], change(kind: str, identity: str) -> None. kind — fixed internal allowlist, identity посилається на verified manifest; no shell/arbitrary command. Linux implementation використовує fixed binaries, shell=False, bounded timeout, categorical errors. Hidden private env snapshots не входять у repr/JSON. LinuxRuntimeHost утримує private in-memory env baseline під час capture; Task2 публікує його як files0600 і завантажує назад для fresh-process inverse. Root ledger у target-key namespace містить safe references на operation state; unfinished записи перевіряються незалежно від нового evidence path. JobChange records з Task3 також зберігаються до executor у private state, не у DB receipts.

### Task 1: Actual runtime manifest і provenance

**Files:** Create services/backend/src/avelren/adoption_runtime.py; Test services/backend/tests/unit/test_adoption_runtime.py.

**Interfaces:** Produces capture_runtime(host: RuntimeHost, checkout: Path) -> RuntimeManifest; encode_runtime(manifest: RuntimeManifest) -> bytes; decode_runtime(payload: bytes) -> RuntimeManifest; runtime_digest(manifest: RuntimeManifest) -> str; verify_runtime(host: RuntimeHost, manifest: RuntimeManifest, *, stopped_ids: tuple[str, ...]) -> None.

Schema format1: host/machine/boot identity; verified candidate source/root; DB container/image; ordered stacks project/directory/compose paths+hashes/services/container IDs/image IDs/networks/mount identities; collector control/volume identity; allowed timer/service names і job IDs. Secret baseline/activity/phase не входять у digest. Actual package provenance перевіряє installed site-packages, а не лише /app/src.

- [ ] **Step1: Write failing tests** test_clone_wrong_host, test_omitted_override, test_unknown_client, test_actual_site_packages_hash, test_secret_not_public, test_env_drift, test_phase_separate_digest. Assert categorical mismatch, zero change calls, sentinel absent JSON/repr/errors, compose-order digest changes, stopped state allowed тільки у stopped_ids.
- [ ] **Step2: Run RED** PYTHONPATH=services/backend/src python -m pytest -c services/backend/pytest.ini services/backend/tests/unit/test_adoption_runtime.py -q -p no:cacheprovider; expected missing implementation. Fake host не підключається до Docker.
- [ ] **Step3: Implement interfaces:** strict fields/types/version/duplicate validation, Docker context/labels/IDs і full inventory; clean candidate SHA/provenance; actual overrides/raw env/mounts; source runtime не змушувати бути all-main. Existing collector helpers — джерело правил, не shell CLI із secret output. Read probes не імпортують entrypoints/writers.
- [ ] **Step4: Run GREEN** той самий focused command; prove every mismatch zero mutations.
- [ ] **Step5: Commit** named module/tests, українське повідомлення, fresh task review.

### Task 2: Host lease, private state, clients/timers

**Files:** Create services/backend/src/avelren/adoption_maintenance_state.py, adoption_maintenance_clients.py; Test services/backend/tests/unit/test_adoption_maintenance_state.py, test_adoption_maintenance_clients.py.

**Interfaces:** Consumes Task1. Produces acquire_maintenance(directory: Path, binding: TargetBinding, manifest: OperationManifest, runtime: RuntimeManifest) -> MaintenanceLease; capture_baseline(host: RuntimeHost, runtime: RuntimeManifest) -> MaintenanceBaseline; append_event(lease: MaintenanceLease, phase: str, record: dict[str, object]) -> None; stop_clients(host: RuntimeHost, baseline: MaintenanceBaseline, lease: MaintenanceLease, *, timeout_seconds: int) -> tuple[str, ...]; pause_timers(host: RuntimeHost, baseline: MaintenanceBaseline, lease: MaintenanceLease, *, timeout_seconds: int) -> tuple[str, ...]; restore_clients(host: RuntimeHost, baseline: MaintenanceBaseline, lease: MaintenanceLease, changed_ids: tuple[str, ...], *, timeout_seconds: int) -> None; restore_timers(host: RuntimeHost, baseline: MaintenanceBaseline, lease: MaintenanceLease, changed_names: tuple[str, ...]) -> None.

- [ ] **Step1: Write failing tests** test_two_paths_one_lease, test_stale_unfinished_blocks_apply, test_partial_stop_observed, test_disabled_timer_stays_disabled, test_foreign_timer_drift, test_spool_identity, test_state_fsync_failure. Assert Caddy first; no DB stop/delete/recreate/spool writes; stopped IDs independently observed; ambiguous change recorded unverified; wrong modes/symlinks/hardlinks refused.
- [ ] **Step2: Run RED** PYTHONPATH=services/backend/src python -m pytest -c services/backend/pytest.ini services/backend/tests/unit/test_adoption_maintenance_state.py services/backend/tests/unit/test_adoption_maintenance_clients.py -q -p no:cacheprovider.
- [ ] **Step3: Implement:** fixed root-owned lock directory outside evidence/checkout, O_NOFOLLOW+flock nonblocking, target-derived key; lease context-manager holds FD until orchestrator ends. Exclusive numbered state events format1 bound to operation/target/runtime/plan, fsync before change and actual observation after. Capture timer active/enabled/service states, wait known running services without kill. Timeout strict int1..300, monotonic.
- [ ] **Step4: Run GREEN** same command; Linux two-helper-process actual flock test, no real systemctl. Restore only originally active clients/timers with matching actual state; do not enable originally disabled timers.
- [ ] **Step5: Commit** named modules/tests, fresh review.

### Task 3: Timescale jobs і fresh quiescence

**Files:** Create services/backend/src/avelren/adoption_maintenance_jobs.py; Test services/backend/tests/unit/test_adoption_maintenance_jobs.py, services/backend/tests/database/test_adoption_maintenance_jobs.py.

**Interfaces:** capture_jobs(conn: psycopg.Connection, allowed_ids: tuple[int, ...]) -> tuple[JobState, ...]; pause_jobs(conn: psycopg.Connection, baseline: tuple[JobState, ...], lease: MaintenanceLease, *, timeout_seconds: int) -> tuple[JobChange, ...]; resume_jobs(conn: psycopg.Connection, changes: tuple[JobChange, ...], lease: MaintenanceLease, *, timeout_seconds: int) -> None; wait_quiescent(dsn: str, binding: TargetBinding, *, timeout_seconds: int) -> None.

- [ ] **Step1: Write failing tests** test_prepaused_not_resumed, test_running_job_timeout, test_unknown_job_refused, test_foreign_definition_drift, test_pause_ack_unknown, test_active_autovacuum_refused. Assert approved alter_job scheduled=false/true only; no catalog UPDATE/terminate/autovacuum SET; fresh running/metadata gap blocks DB executor.
- [ ] **Step2: Run RED** focused unit; DB AVELREN_ADOPTION_TEST_SELECTOR=adoption_maintenance_jobs bash scripts/test_database.sh adoption, owned disposable project.
- [ ] **Step3: Implement:** verify target/version before each mutation session; full fresh jobs inventory must exactly match allowed IDs. Durable intent → official alter_job → independent read observation. Mutable job_status/statistics separate from immutable definition. Resume exact match of own paused metadata only. Bounded fresh probes, all job/quiescence connections closed before DB executor. Unknown pause/resume not retried; existing require_quiescent/allowlist unchanged.
- [ ] **Step4: Run GREEN** focused unit+named DB subset pinned2.30.1: prove actual jobs/job_stats layout, scheduled/status transitions, running refusal, metadata preservation. Unsupported built-in job layout is blocker requiring concrete plan clarification, not implicit allowlist.
- [ ] **Step5: Commit** module/tests, fresh review; no live DB.

### Task 4: Orchestrator і результат відновлення runtime

**Files:** Create services/backend/src/avelren/adoption_maintenance.py; Test services/backend/tests/unit/test_adoption_maintenance.py.

**Interfaces:** VerifiedRuntime(host: RuntimeHost, baseline: MaintenanceBaseline, lease: MaintenanceLease) implements verify(context: MaintenanceContext, manifest: OperationManifest) -> None and checkout_roots() -> tuple[Path, ...]. Produces run_maintenance(action: str, dsn: str, binding: TargetBinding, plan: AdoptionPlan, evidence_dir: Path, host: RuntimeHost, confirm: Callable[[str, OperationManifest], Confirmation], execute: ProductionExecutor, *, timeout_seconds: int) -> MaintenanceOutcome. ProductionExecutor protocol __call__(dsn: str, binding: TargetBinding, plan: AdoptionPlan, evidence_dir: Path, context: MaintenanceContext, confirmation: Confirmation, runtime: RuntimeVerifier) -> AdoptionResult matches existing apply_production/inverse_production exactly.

- [ ] **Step1: Write failing tests** test_refusal_no_changes, test_partial_stop_verified_restore, test_unknown_stays_paused, test_accepted_restart_failure_rc5, test_env_image_drift_before_restart, test_inverse_fresh_context, test_signal_each_phase, test_concurrent_through_restart. Assert executor at most once/no auto inverse; ingress last; only owned original active states restored; DB status unchanged by restart failure; unknown/drift no resume; fresh inverse uses retained original baseline.
- [ ] **Step2: Run RED** PYTHONPATH=services/backend/src python -m pytest -c services/backend/pytest.ini services/backend/tests/unit/test_adoption_maintenance.py -q -p no:cacheprovider.
- [ ] **Step3: Implement sequence:** lease → verify fresh target/evidence/baseline/runtime → preview+confirmation → durable private baseline → pause known timers/jobs and stop ingress/clients → actual stopped/quiescent → MaintenanceContext phase exactly quiescent → one executor → durable DB outcome → outcome-permitted restart/acceptance. Callback verifies actual lease/runtime/phase every time; context JSON/timestamp alone never sufficient.
- [ ] **Step4: Implement policy and run GREEN:** verify target/fingerprint/outcome before restore; exceptions after possible SQL without proof become unknown. Verified zero-write refusal/rollback restores only owned changes. Verified inverse: action INVERSE, status rolled_back/category None, inverse-accepted receipt і before fingerprint; forward rolled_back не є inverse success. Adopted/already_target/verified inverse restores clients and accepts locally, restores matching jobs/timers, ingress last. Restart failure rc5 records original db_status and mixed runtime, ingress closed. HUP/INT/TERM requests bounded phase-aware stop, never blind EXIT restart. Record/lease loss after possible commit cannot become verified rollback.
- [ ] **Step5: Commit** module/test, fresh review. Explicit test distinguishes existing AdoptionError before vs after executor, no assumption that every exception implies zero SQL.

### Task 5: Operator CLI та production composition root

**Files:** Create services/backend/src/avelren/adoption_maintenance_cli.py, ops/postgres-production-adoption.sh, services/backend/tests/unit/test_adoption_maintenance_cli.py, ops/postgres-production-adoption-contract-test.py; Modify ops/POSTGRES-ADOPTION.md, docs/POSTGRES-ADOPTION-PRODUCTION-RUNBOOK.md.

**Interfaces:** main(argv: list[str] | None = None) -> int. CLI python -m avelren.adoption_maintenance_cli apply|inverse --evidence-dir ABSOLUTE --runtime-manifest ABSOLUTE --timeout-seconds 1..300; only AVELREN_ADMIN_DSN. Private files: snapshot.json/snapshot.sha256, plan.json/plan.sha256 (existing verified APIs), target.json/target.sha256 (existing target encoder/decoder), production-operation.json/production-operation.sha256 (existing operation APIs). Separate read-only capture-runtime --output ABSOLUTE publishes exclusive private manifest. Команда prepare --evidence-dir ABSOLUTE --runtime-manifest ABSOLUTE перевіряє existing snapshot/plan/checksums і actual source/runtime/target, capture_target через read-only connection, exclusive target binding + make_operation/write_operation; не змінює roles/schema. Файлове evidence capture на сервері потребує окремого дозволу. Existing файли не overwrite; неповна публікація блокує apply. Додати test_prepare_read_only_and_exclusive: нуль DB/host mutation, правильні digests, foreign binding/partial files refused.

- [ ] **Step1: Write failing tests** test_root_tty_before_change, test_bad_phrase_zero_mutation, test_test_env_empty_refused, test_no_injection_flags, test_error_secret_sanitized, test_exit_codes, test_inverse_fresh_confirmation. Assert no argv DSN/confirmation/force/yes/hooks; only concrete adapters; sanitized JSON db_status/runtime_status/category/exit_code; codes0..5; secret YAML capture refused.
- [ ] **Step2: Run RED** focused pytest and isolated external-binary contracts; no actual systemctl/Docker service changes.
- [ ] **Step3: Implement:** Linux root/TTY/test-env checks before mutation; existing confirm_operator exact phrase; preview action/opID/target/full plan and maintenance changes. Source entrypoint stays closed until Task6 accepted, no environment bypass. Wrapper executes verified candidate Python only; no DSN/test hooks; Git executable100755. No production flags expose injected objects.
- [ ] **Step4: Run GREEN** focused tests; python ops/postgres-production-adoption-contract-test.py; bash -n ops/postgres-production-adoption.sh. Docs distinguish capture/source readiness, maintenance, inverse, unknown and separate operational GO; no apply-test live usage.
- [ ] **Step5: Commit** named source/tests/docs, fresh review.

### Task 6: Реальна isolated rehearsal, CI та handoff

**Files:** Create ops/compose.adoption-maintenance-test.yml, ops/postgres-maintenance-adoption-test.sh, services/backend/tests/rehearsal/test_adoption_maintenance_runtime.py; Modify .github/workflows/database.yml, scripts/verify_ci_scopes.py, docs/POSTGRES-ADOPTION-PRODUCTION-RUNBOOK.md, ops/POSTGRES-ADOPTION.md, docs/MIGRATION-REMAINING.md, docs/RELEASE-READINESS.md. CI path filters backend-core/api/watchdog only if new paths require them.

**Interfaces:** bash ops/postgres-maintenance-adoption-test.sh creates owned internal network, pinned Timescale2.30.1, real synthetic clients in main/standalone collector layouts, private evidence and spool volume. Real LinuxRuntimeHost Docker behavior uses explicit synthetic harness identities, not public CLI test flags. Systemd contracts use fake state/action port, never CI host units: actual systemd acceptance before server GO remains separate.

- [ ] **Step1: Write failing rehearsal:** forward→gate→restart and fresh explicit inverse; real stop/start both layouts; raw/CAGG/compressed data, full journal/functions/ACL probes7roles, same container/image IDs, SQLite/spool bytes+volume identity. Clone/override/image/private-env drift rejects; no pull/build/recreate/migrate/unknown stops; concurrent operation blocked through runtime acceptance.
- [ ] **Step2: Run RED** owned runner before wiring; actual partial stop+controlled restart failure, HUP/INT/TERM and injected unknown outcome assert ingress closed/jobs paused/no SQL retry/inverse. Injections Python harness only. No real єЧерга/FCM/cloud.
- [ ] **Step3: Implement runner/CI:** pinned images, owned labels cleanup/resources assertions; autovacuum=off only synthetic rehearsal DB and explicit production refusal test retained. Timer fakes supplement real Docker/DB/volume proof. Relevant workflow/scopes include runner; measure actual total50min job budget. If exceeded, separate scoped CI job, not timeout increase/test exclusions. Actions budget$3 unchanged.
- [ ] **Step4: Run GREEN acceptance:** runner+jobs subset, full backend unit once at final source, Ruff, python scripts/verify_ci_scopes.py, python scripts/verify_core_provenance.py, Bash syntax/diff. Record exact head/counts/images/layouts/fail phases/cleanup; don't rerun broad suites without changes/failures. Fresh final whole-branch review after task reviews.
- [ ] **Step5: Commit docs/CLI acceptance:** open source CLI only with complete local acceptance; merge requires review+exact-head relevant CI. Record source/local/CI/merge separately from deployment/phone. PR attached; server/DSN/systemd operational unaccepted; old repos retained.

## Критерії завершення та окремий серверний GO

- [ ] Шість task reviews, blockers fixed with scoped rereview, final whole-branch review.
- [ ] Exact-head relevant CI SUCCESS, merge verified; source readiness documented.
- [ ] Production CLI accepted in source; disposable guards/formats unchanged.
- [ ] Before production: fresh read-only topology audit, actual off-host backup checksum+isolated restore, exact source/runtime/target/plan, runtime rollback/window, separate owner GO. Plan не дозволяє виконати ці серверні записи.
- [ ] DSN cutover, legacy-role retirement, PostgreSQL/SQLite recovery, live monitor acceptance і видалення старих repos лишаються окремими роботами.

## Self-review

Coverage: runtime/provenance/clone Task1; durable state/concurrency/clients/timers/spool Task2; jobs/quiescence Task3; partial/unknown/inverse/restart/signals Task4; root/TTY/secrets/codes Task5; pinned real runtime/DB/volumes/CI/docs Task6. All five Review Focus cases have named tests. Types match existing seven-argument executor and quiescent MaintenanceContext. Job immutable metadata/statistics separated; host lease independent DB lock. No new ownership SQL, receipt schema, migration, DSN/password changes. Actual systemd/production backup acceptance explicitly outside synthetic proof.

Локальні команди Python/pytest виконувати у вже перевіреному Linux test image з read-only bind mount/PYTHONPATH; якщо host має pytest — допускається наведена пряма команда. Не встановлювати залежності на production заради тестів. Docker mount checkout не перемикати під час запуску.
