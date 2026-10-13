# Узгоджене резервування PostgreSQL + SQLite — план реалізації

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Створювати перевірений зашифрований комплект SQL + SQLite та довести його ізольоване відновлення без пропусків і дублів.

**Architecture:** Host coordinator коротко призупиняє лише DB writer, формує SQL та SQLite copies, підтверджує повернення writer і лише потім виконує bounded upload. Completion manifest пов'язує артефакти; state/lock/recovery захищають незавершений запуск. Native restore/replay залишаються основою приймання.

**Tech Stack:** Python 3.12+ host standard library, Python backend з чинного lock, Bash, Linux flock/systemd, Docker, PostgreSQL 16/TimescaleDB, SQLite Online Backup, rclone crypt.

**Spec:** [Погоджений дизайн](../specs/2026-10-13-paired-postgres-sqlite-backup-design.md), commit `d09bc9907cb111fff5d6592493b312294e9504d2`.

## Global Constraints

- Початковий main `c7419ae8cccd719c05a42ca61981d85b2bdc0410`; гілка `codex/paired-backup-20261013`. Чужий незавершений maintenance adapter не використовувати.
- Один producer, початки запитів через 60 секунд, незмінні Device ID/endpoint/headers/error policy; тести без єЧерги/FCM.
- Capture-only window ≤900 seconds, copy budget 720 seconds, cancellation/off reserve 180 seconds; network stage ≤900 seconds після off ACK.
- Crypt remote обов'язковий. Retention 7 daily / 4 weekly / 3 monthly; legacy SQL-only не видаляти під час початкового ввімкнення.
- 0700 private directories, 0600 artifacts/state; без credentials/DSN/payloads/raw errors у manifests/logs/argv.
- Не змінювати migrations/roles/DSN/collector rhythm/Android. Не відкривати production restore CLI.
- Усі production mutations — лише після окремого GO на конкретний перевірений пакет. Цей план дозволяє source/local/CI підготовку.
- Виконання погоджено окремими агентами; незалежний перегляд кожної задачі та всієї гілки. Письмовий перегляд цього плану перед реалізацією.

## Review Focus

1. On timeout після запису capture-only intent: cleanup має врахувати вже змінений режим (задачі 2–3).
2. SIGKILL із живим helper/передачею lock: не відновлювати writer до завершення дочірніх mutations (2–3).
3. Чужий capture-only або новий container identity: не вимикати чужу паузу (2–3).
4. ACKed SQLite відсутній у SQL або pending вже committed: fail closed у першому випадку, exact idempotent retry у другому (4).
5. Quota/partial upload/mixed-date manifest: не видавати успішну пару/stamp і не тримати writer paused (1, 3, 4).

## Файли та межі компонентів

- Backend `paired_backup_spool.py`: native Online Backup, offline inspection й pair-to-primary validation; без HTTP.
- Host `ops/paired_backup_manifest.py`: versioned manifest/names/hashes/retention без backend dependencies.
- Host `ops/paired_backup_state.py`: durable state, shared lock, child lifetime/deadlines, owner recovery.
- Host `ops/paired-backup.py`: coordinator/CLI, SQL/SQLite/remote adapters; `ops/backup.sh` — mode dispatcher зі збереженим SQL-only contract.
- `ops/paired-restore-rehearsal.sh` і acceptance driver: тільки isolated pair restore/replay.
- Existing runtime control/maintenance/restore entrypoints: active-backup guard до mutations; закриті CLI не відкривати.
- Tests/CI/docs: component-focused перевірки; provenance існуючих перенесених файлів не переписувати довільно.

### Task 1: SQLite helper та completion manifest

**Files:** Create `services/backend/src/avelren/paired_backup_spool.py`, `services/backend/tests/unit/test_paired_backup_spool.py`, `ops/paired_backup_manifest.py`, `ops/paired-backup-manifest-contract-test.py`.

**Interfaces:**
- `snapshot_spool(source: Path, destination: Path) -> dict`: `SpoolStore.backup_to`, destination поза source directory, повертає summary зі schema/version/state_counts/payload_count/range/hash/bytes. Після snapshot inspect static copy; не виводити payloads.
- `inspect_spool(path: Path) -> dict`: immutable readonly static copy, integrity/schema/all payloads; started без payload припустимий, incomplete pending — error.
- Backend CLI `python -m avelren.paired_backup_spool snapshot --source PATH --output PATH` та `inspect --source PATH`; JSON summary stdout, категорійні errors stderr, nonzero failure.
- Host `build_manifest(backup_id: str, artifacts: dict, snapshots: dict, runtime: dict, spool: dict, writer_resumed: bool) -> dict`, `validate_manifest(value: object) -> dict`, `verify_local_pair(manifest: dict, directory: Path) -> dict`, `retention_candidates(manifests: list[dict], tier: str, keep: int) -> list[str]`.
- Schema `format_version=1`; backup_id `YYYYMMDD-HHMMSS`; tier daily/weekly/monthly. Exact SQL/spool names з spec; artifact records `name,sha256,bytes`, sha256 lowercase64. Snapshot records `started_at,finished_at` UTC; runtime `source_commit,image_id,container_id,restart_count,started_at`; spool summary з helper; writer_resumed має бути true. Невідомі поля/версія, duplicate JSON keys, path traversal/absolute basenames, змішані IDs — reject.
- `pair.json` є completion record; містить hashes/bytes обох compressed artifacts, не власний hash. Sidecars однозначно задають compressed artifact hashes.

- [ ] Написати failing helper tests: `test_online_snapshot_preserves_pending_wal` (5 pending, hashes незмінні), `test_inspect_accepts_started_without_result`, `test_invalid_pending_digest_or_version_fails`, `test_snapshot_destination_inside_live_directory_rejected`.
- [ ] Написати failing manifest tests: `test_exact_same_id_pair`, `test_missing_writer_ack_rejected`, `test_duplicate_keys_unknown_version_and_path_escape_rejected`, `test_mixed_ids_and_bad_hash_rejected`, `test_partial_pair_rejected`, `test_retention_only_complete_paired_groups` (keep 7/4/3, newest protected, legacy untouched).
- [ ] Run RED: `python -m pytest -c services/backend/pytest.ini services/backend/tests/unit/test_paired_backup_spool.py -q`; `python3 ops/paired-backup-manifest-contract-test.py`. Відсутні interfaces мають спричинити FAIL.
- [ ] Реалізувати interfaces та GREEN тими самими commands. Без нових залежностей. Native helper не запускає producer/replay.
- [ ] Commit лише task files; незалежний review requirements+code до задачі 2.

### Task 2: Lease, runtime guard і аварійне повернення

**Files:** Create `ops/paired_backup_state.py`, `ops/paired-backup-state-contract-test.py`; Modify `ops/collector-runtime-control.py`, `ops/collector-runtime-control-contract-test.py`, `ops/maintenance-window.sh`, `ops/maintenance-reboot.sh`, `ops/restore-production.sh`; Create `ops/paired-backup-guard-contract-test.sh`.

**Interfaces:**
- `backup_lock(state_dir: Path)` context manager: O_NOFOLLOW, private root-owned single-link regular lock, flock nonblocking. Shared paths `operator-backup.lock` та `paired-backup-state.json` у runtime state_dir.
- `write_state(state_dir: Path, value: dict) -> None`, `read_state(state_dir: Path) -> dict | None`: atomic fsync file+directory, format_version1, generation UUID, owner PID/process-start/boot ID, exact container identity, phase, timestamps; без секретів. Phases `prepared,on_intent,paused,copied,off_intent,resumed,published,failed,recovery_required`.
- `assert_no_backup(state_dir: Path) -> None`: active lock або unresolved durable state блокує чужу mutating command; readonly commands проходять.
- Mutating operator entrypoints тримають той самий `backup_lock` від перевірки state до завершення mutation; одноразова перевірка без lock недостатня через race. Lock order завжди backup lock → existing control lock. Coordinator тримає backup lock та викликає internal validated controller з власною typed authority, не повторно бере той самий lock.
- `run_bounded(argv: list[str], *, deadline: float, env: dict | None = None, stdout_path: Path | None = None) -> int`: own process group, deadline/signal cancellation, kill/reap children before returning/lease release; redact errors. Lock authority не має залишати працюючий mutating child після parent death.
- `recover_owned_run(state_dir: Path, *, runtime: object) -> dict`: тільки під lock, перевірка generation/identity/owner death, завершення children, off/ACK для власного intent. Takeover/unproven ownership -> recovery_required без off.
- Coordinator internal controller commands виконуються через existing validated `execute` під власною authority; public runtime CLI не має generic env-variable bypass. Усі ці guard changes залишають default runtime behavior без active lease незмінним.

- [ ] RED tests: simultaneous runs rejected; symlink/hardlink/foreign-owner paths rejected; atomic state survives interruption; on-intent timeout recoverable; initially paused never changed; stale PID із іншими start/boot rejected; changed container/restart count never off.
- [ ] RED lifetime tests на Linux: SIGTERM та SIGKILL parent з реальним child/grandchild marker; після recovery нема mutations/descendants; наступний owner не стартує, поки попередній helper живий. Timeouts тестуються короткими injected deadlines, production constants не змінювати.
- [ ] RED guard harness: start/stop/restart/capture-only та modern maintenance/reboot/restore mutations rejected before external mutation при lease/unresolved state; existing readonly/closed-CLI behavior retained. Legacy direct Docker bypass позначити runbook restriction, не вигадувати його блокування.
- [ ] Реалізувати й GREEN: `python3 ops/paired-backup-state-contract-test.py`; `python3 ops/collector-runtime-control-contract-test.py`; `bash ops/paired-backup-guard-contract-test.sh`; чинні maintenance/restore contract scripts для змінених entrypoints.
- [ ] Commit та independent review. Не переносити unverified adapter з іншої гілки.

### Task 3: Coordinator та encrypted off-host publication

**Files:** Create `ops/paired-backup.py`, `ops/paired-backup-contract-test.py`; Modify `ops/backup.sh`, `ops/backup-contract-test.sh`, `ops/avelren-backup.service`; Create `ops/avelren-backup-recovery.service`, `ops/paired-backup-unit-contract-test.py`.

**Interfaces:**
- CLI `paired-backup.py run --manifest PATH --state-dir PATH --work-dir PATH --stack-dir PATH --remote REMOTE --rclone-config PATH --receipt PATH`; `recover --manifest PATH --state-dir PATH`. Root Linux production; test mode uses only validated synthetic identities.
- Environment secrets stay inherited: AVELREN_BACKUP_PASSWORD/DB role pinned avelren_backup; never DSN/password args. Explicit SQL Compose context/db identity; preserve production override/pin.
- Consume helper Task1 and state Task2; coordinator deadline 720s critical-copy/900s pause total, 900s network; on/off ACK 30s existing contract, remaining budget enforced externally.
- Runtime manifest pins collector image/volume; compatible helper script/source hash checked before run, helper network none/UID10001/private output outside live volume. No collector recreation or image latest.
- `backup.sh` dispatch `AVELREN_BACKUP_MODE=sql-only|paired`, default sql-only for source backwards compatibility. Paired mode requires valid runtime manifest, never silently falls back. Production package explicitly selects paired mode after GO; SQL-only receipt is not paired acceptance.
- Existing success stamp/receipt written only after resumed ACK + complete remote pair verification + successful retention. Paired receipt includes backup_id/manifest hash/remote paths and safe counts/times. Failure preserves existing stamp and never creates successful receipt.
- Unit wiring: backup service OnFailure to recovery service and ExecStopPost bounded recovery; kill entire unit cgroup. Run timeout ≤1800s, stop recovery ≤180s; recovery unit/ExecStopPost idempotent and serialized by shared lock. Reboot recovery remains explicit runbook step.

- [ ] RED fake-runtime/rclone tests order: preflight→onACK→SQL→SQLite→identity check→offACK→upload4files→remote hash/size→manifest-last→readback→retention→stamp. Assert upload never while paused.
- [ ] RED faults: cryptwrong, existing pause, on timeout after intent, dump/helper timeout, identity/restart change, off timeout, signals; assert owned off attempts only, pending preserved, deadline cleanup, no stamp/receipt success.
- [ ] RED publication faults: quota/failed readback/missing file/wrong size/hash/manifest partial; network bounded, writer already resumed; no deletion of newest/legacy, secret text absent from logs/argv.
- [ ] RED unit contracts: actual executable/recovery paths, timeout/kill policy/permissions, no masked recovery failure. Re-run SQL-only `backup-contract-test.sh` unchanged assertions.
- [ ] Implement/GREEN: `python3 ops/paired-backup-contract-test.py`; `python3 ops/paired-backup-unit-contract-test.py`; `sudo bash ops/backup-contract-test.sh`; `bash -n ops/backup.sh`; `systemd-analyze verify` units with fixture executables installed only in isolated Linux environment.
- [ ] Commit та independent review; жодних production commands.

### Task 4: Native pair restore й точна звірка ACK/pending

**Files:** Modify `services/backend/src/avelren/paired_backup_spool.py`; Create `services/backend/tests/database/test_paired_backup_recovery.py`, `ops/paired-restore-rehearsal.sh`, `ops/paired-restore-acceptance.py`, `ops/paired-restore-contract-test.py`, `ops/compose.paired-restore-test.yml`.

**Interfaces:**
- Backend `async verify_acked_primary(store: SpoolStore, conn: AsyncConnection) -> dict`: decode every ACKed payload; existing `verify_committed_cycle` exact comparison. Counts insufficient; no ACK reset/update/prune.
- Rehearsal CLI `bash ops/paired-restore-rehearsal.sh --directory PATH --manifest BASENAME`: source pair read-only; unique own project/internal network/volume/no ports; pinned Timescale image; copies SQLite into own writable directory.
- Verify Task1 manifest/hash/size/gzip/schema first. Native `ops/restore.sh`/engine + verify with disposable identity only. Then verify ACKed, recover_started, explicitly release restored capture-only on OWN copy, FIFO replay; count and exact-value evidence, cleanup on every exit.
- Manifest without pair/mixed IDs or missing ACKed primary fails before replay, preserves inputs; legacy SQL-only remains readable by old restore but new paired reader refuses it.

- [ ] RED DB tests: mixed 2 ACKed/3 pending/1 started fixture; SQL dumped during ACKed freeze; restore owns database. Assert ACKed unchanged; all pending+interrupted become primary exactly once; no invented observations for started; source files hashes unchanged.
- [ ] RED DB tests: committed pending before ACK retry -> one primary row; missing/mismatched ACKed -> zero replay mutations; conflicting pending -> retained; delayed cycles no new alerts/ETA/FCM.
- [ ] RED shell/reader contracts: production name/DSN/volume refused, path escapes/malformed gzip/incomplete pair refused, cleanup only own resources.
- [ ] Implement/GREEN: `bash scripts/test_database.sh` includes new DB module; `python3 ops/paired-restore-contract-test.py`; `bash ops/paired-restore-rehearsal.sh --directory <synthetic-pair> --manifest <pair-name>`.
- [ ] Commit та independent review. Native production restore guards не послаблювати.

### Task 5: Real daemon rehearsal, CI і операційна документація

**Files:** Create `ops/paired-backup-integration-test.sh`, `ops/paired-backup-daemon-test.py`, `ops/compose.paired-backup-test.yml`, `docs/audits/PAIRED-BACKUP-SOURCE-2026-10-13.md`; Modify `.github/workflows/database.yml`, `.github/workflows/backend-core.yml`, `ops/RECOVERY.md`, `ops/COLLECTOR-SPOOL.md`, `ops/COLLECTOR-RUNTIME.md`, `docs/MIGRATION-REMAINING.md`, `docs/RELEASE-READINESS.md`.

**Interfaces:** Real daemon with synthetic HTTP transport, explicit 60-second rhythm, separate project/internal network; local crypt filesystem remote for rclone verification, synthetic secrets. Use Task3 coordinator and Task4 restore, no upstream/Drive calls.

- [ ] Написати failing integration acceptance: мінімум 3 producer cycles (до/під час/після backup), same persistent synthetic ID, starts ≥60s apart; writer ACK→copies→off/drain; no second producer; API smoke remains accessible. Local crypt bytes differ from plaintext; readback matches manifest; isolated restored exact cycles/observations pass.
- [ ] Додати actual SIGKILL coordinator recovery case в цьому fixture: writer resumes only for owned intent після child termination; restart/drain proof. Root-confirmed Docker cleanup after harness.
- [ ] Implement/GREEN `bash ops/paired-backup-integration-test.sh`, потім meaningful narrow regressions existing collector/runtime/backup/restore contracts. Не повторювати довгі suite без нової причини.
- [ ] Додати helper unit coverage до existing backend workflow; host contracts/systemd/integration до existing database workflow. Зберегти всі чинні tests/SBOM/timeouts; CI classifier мусить маршрутизувати всі new ops/backend paths, перевірити його tests. Не додавати scheduled remote jobs/нові workflow без потреби.
- [ ] Документація: source vs hosted CI vs installed production vs real paired restore; dated SQL/SQLite evidence; legacy commands restriction; package files/hashes/helper image/unit config; bounded first-run/rollback/reboot recovery; no accepted RPO/RTO before measured real pair. Узгодити default sql-only vs intended paired installation явно.
- [ ] Run GREEN source checks `python3 scripts/verify_core_provenance.py`, `python3 scripts/verify_android.py`, backend Ruff/unit, affected Bash syntax + new host contracts, `git diff --check`.
- [ ] Commit; independent task review і whole-branch review. Виправити findings з доказами, далі PR із exact-head hosted CI; attach PR. Merge лише після passing required gate/review. Server deployment окремим конкретним GO.

## Self-review та виконання

Spec coverage: helper/schema/WAL/format/retention→1; ownership/deadlines/SIGKILL/guards→2; capture sequencing/crypt/stamp/units→3; ACK consistency/native restore/replay→4; producer/CI/docs/package/acceptance→5.
Review Focus всі 5 conditions мають named assertions у відповідних tasks.
Interfaces Task1/2 використовуються Task3/4; жодних нових dependencies чи production API.

Перед dispatch кожен агент читає AGENTS.md, CONTRIBUTING.md, INTEGRATION.md,
цей spec і plan. Після кожної задачі source commit+tests+незалежний review.
Runtime helper image/source hashes і exact installation paths визначаються
з фактичного merged main перед production пакетом, не вигадуються в плані.

План підготовлений для письмового перегляду власником. Реалізація починається
після цього перегляду; execution method збережено — окремі агенти та review.
