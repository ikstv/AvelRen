# Єдиний CI-gate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Погоджений метод: новий виконавець та окремий review кожної задачі; фінальний review гілки.

**Goal:** Єдиний строгий `CI gate` для потрібних компонентів одного commit.

**Architecture:** Повний Git diff → scopes → 8 reusable workflows → strict needs gate. Classifier/evaluator — Python-функції та CLI; protection окремо.

**Tech Stack:** GitHub Actions, Git, Python >=3.12 stdlib; чинні pytest 9.1.1, PyYAML 6.0.3, Ruff 0.16.8; Linux test environment із jq.

**Spec:** `docs/superpowers/specs/2026-10-12-ci-aggregate-gate-design.md`, commit `2f26af22970227448a8d0ebf9866e122faf7709b`. Читати разом із планом.

## Global Constraints

- `pull_request` без paths/branches: opened, synchronize, reopened, ready_for_review, edited; draft теж. `push.branches: [main]`; без schedule/feature push.
- Repository завжди; supply_chain для main PR/push. **13 cases × дві події = 26 перевірок**.
- Gate: name `CI gate`, needs scope + 8 calls, `if: ${{ always() }}`, timeout 2 хв. Required тільки success; non-required success/skipped; решта — failure.
- Checkout одного `github.sha`, persist-credentials:false; scope fetch-depth:0. Permissions contents:read; без secrets/inherit, write/OIDC, API polling, довільних ref/command inputs.
- Зберегти bodies/pins/versions/digests/timeouts, негативні shell-тести, artifacts. SBOM: обидва jobs, cleanup always(), validation перед upload, SHA names, retention 30, missing=error, без docker push.
- Live external-health-monitor.yml лишається manual-only поза CI із власним issues:write. Fork Gradle cache-read-only зберігається.
- Actions $3/місяць не дозволяє billing/Pro/visibility/access/App/production змін. Missing CI не pass; enforcement off — окремий блокер.
- Українські docs/коміти/PR; зберегти FCM зміни й аудити. Реалізація після погодження плану.

## Review Focus

- Edited після failure повторює jobs — Task 4.
- Rename/delete/newline/Unicode/shell filenames без виконання вводу — Task 2.
- scripts/new-tool.py не стає безпечним через repository catchall — Task 1.
- Старий SHA, missing/malformed outputs чи неповний needs → failure — Task 3.
- Main run не витісняється новим push — Task 4.

---

## Файли й спільний контракт

Створити `.github/ci-scopes.json`, `.github/workflows/ci.yml`, `scripts/ci_scopes.py`, `scripts/verify_ci_gate.py`, `scripts/tests/test_ci_scopes.py`, `scripts/tests/test_ci_gate.py`, `scripts/tests/test_ci_workflow_contract.py`. Змінити 8 workflows нижче, `scripts/verify_ci_scopes.py` і три docs із Task 5.

| Manifest/output/caller ID | Workflow | Незмінні internal jobs |
| --- | --- | --- |
| backend_core | backend-core.yml | core |
| api | api.yml | api |
| database | database.yml | database |
| watchdog | watchdog.yml | watchdog |
| android | android.yml | android |
| repository | repository.yml | repository |
| monitor_contracts | external-monitor-checks.yml | monitor-contracts |
| supply_chain | supply-chain.yml | source-sbom, image-sbom |

Manifest exact keys: `version: 1`, `components: {ID: {workflow: str, paths: list[str]}}` (8 IDs), `all_components_paths: list[str]`, `docs_only_paths: list[str]`. Repository paths зберігаються; supply_chain paths порожні. Always/event правила явні у classifier.

Plan exact keys: `version: 1`, `complete: bool`, `reason: str`, `event: str`, `base_sha: str|null`, `head_sha: str`, `tested_sha: str`, `required: {ID: bool}`. Reasons: matched, control_change, unknown_path, new_branch, history_unavailable, diff_unavailable. Complete=true означає повне покриття вибору, включно з all fallback. Invalid manifest/event/tested revision → nonzero без придатних outputs.

Команди — з кореня Linux checkout. Перед Task 1: using-git-worktrees, ізоляція від інших writers, актуальний baseline із FCM. Tasks послідовні: свіжий виконавець → review. Локальні commits; один фінальний push/PR.

## Task 1: Manifest і classifier

**Files:** `.github/ci-scopes.json`, `scripts/ci_scopes.py`, `scripts/tests/test_ci_scopes.py`.
**Interfaces:** `COMPONENT_IDS: tuple[str,...]`; `load_manifest(path: Path) -> dict`; `match_path(path: str, pattern: str) -> bool`; `classify_paths(paths: Sequence[str], manifest: Mapping, *, event_name: str, target_branch: str) -> tuple[dict[str,bool], str]`. Invalid input → ValueError; без Git/network.

- [ ] RED `test_legacy_26_scopes`: незалежні expected 13 cases чинного verifier × PR/push main. Legacy subset дорівнює старому expected (backend-core → backend_core); repository/supply_chain true. Expected не генерувати з manifest.
- [ ] RED `test_docs_only`: RELEASE-READINESS.md → repository/supply_chain; `test_non_main_pr`: docs → repository; `test_api_contract`: schemas.py/surge*.py → Android + 4 backend; `test_monitor`: classifier/старі monitor tests → monitor_contracts + always; `test_provenance_precedes_docs`: чинні provenance/assets залежності.
- [ ] RED `test_unknown_path`: scripts/new-tool.py, root config, docs/new.json → all на main; `test_control_change` → all; empty diff → always; docs+code не приглушує code. `test_glob`: docs/**/*.md matches docs/a.md і docs/a/b.md; * не перетинає slash; negation/absolute/.. pattern/unsupported syntax → ValueError.
- [ ] RED: `python -m pytest scripts/tests/test_ci_scopes.py -q -p no:cacheprovider`; missing interface.
- [ ] Реалізація: перенести positive paths 7 filtered workflows, перевіривши PR/push рівність. All-controls: .github/workflows/**, .github/ci-scopes.json, scripts/ci_scopes.py, scripts/verify_ci_gate.py, scripts/verify_ci_scopes.py і 3 нові tests exact paths. Docs allowlist: docs/**/*.md, README.md, CONTRIBUTING.md, AGENTS.md, INTEGRATION.md. Пріоритет controls → component matches → docs → unknown/all; repository catchall не доводить безпечність. ** — цілий сегмент 0+ сегментів; * — 0+ символів одного сегмента; решта literal. Non-main normal supply_chain=false; all/control fallback запускає всі 8 — окремий test цього консервативного винятку.
- [ ] GREEN: повторити pytest, exit 0. Stage лише task files; commit `ci: визначити єдині правила вибору перевірок`; review Task 1.

## Task 2: Git diff і scope CLI

**Files:** `scripts/ci_scopes.py`, `scripts/tests/test_ci_scopes.py`.
**Interfaces:** Task 1; `collect_changed_paths(repo: Path, *, event_name: str, event: Mapping, tested_sha: str) -> tuple[list[str]|None, str|None, str, str]` = paths/base_sha/head_sha/reason; `build_plan(repo: Path, manifest: Mapping, *, event_name: str, event: Mapping, tested_sha: str) -> dict`; `main(argv: Sequence[str]|None=None) -> int`.
CLI: `python3 scripts/ci_scopes.py --manifest .github/ci-scopes.json --plan-file <path>`; env GITHUB_EVENT_NAME, GITHUB_EVENT_PATH, GITHUB_SHA, GITHUB_OUTPUT, GITHUB_STEP_SUMMARY.

- [ ] RED disposable tmp_path Git repos, fixture-only identity, shell=False. `test_pr_full_diff`: два head commits враховані; `test_merge_delta_union`: додатковий merge-tree path врахований; `test_push_diff`: before..after; `test_force_updated_head`: новий event не використовує старий diff.
- [ ] RED `test_rename_both_sides` code↔docs; `test_delete`; `test_nul_filenames`: space/Unicode/newline/$(touch sentinel), sentinel не створюється. `test_large_diff`: 301 і 3001 docs paths + останній Android path → android true. Реальні Linux filenames, не лише mock рядки.
- [ ] RED `test_revision_identity`: HEAD=tested_sha; PR 2 parents, parent1=event base.sha, parent2=head.sha; push after=tested_sha, ref=refs/heads/main. Mismatch/bad SHA/invalid event/feature push → fatal без outputs. `test_fallback`: zero before → all/new_branch; missing history/merge-base → all/history_unavailable; diff error → all/diff_unavailable. Unknown tested revision не fallback; empty diff не failure.
- [ ] RED `test_cli_outputs`: exact schema; compact ASCII-escaped plan JSON + 8 ID=true|false рядків, без raw filenames. File/summary містять base/head/tested SHA і reason; fatal exit !=0 без success outputs.
- [ ] RED command: `python -m pytest scripts/tests/test_ci_scopes.py -q -p no:cacheprovider`.
- [ ] Реалізація: 40 lowercase hex SHA до Git calls; звірити HEAD/parents. PR target із base.ref, push main із ref. PR paths = union merge-base(base,head)..head та parent1..tested; push before..tested. Git argv: `git --no-pager diff --no-ext-diff --no-textconv --name-only -z --no-renames <old> <new> --`; bytes split NUL, shell=False. Checkout забезпечує історію; missing objects → fallback без API/секретів. Нерозбірливий filename → all, не ignore. Outputs лише після validation і запису plan.
- [ ] GREEN: pytest вище; `python -m py_compile scripts/ci_scopes.py`; commit task files `ci: визначати зміни за повною Git-історією`; review Task 2.

## Task 3: Строгий evaluator

**Files:** `scripts/verify_ci_gate.py`, `scripts/tests/test_ci_gate.py`.
**Interfaces:** `evaluate(plan: object, needs: object) -> list[str]` ([] = pass, malformed input без traceback); `main(argv: Sequence[str]|None=None) -> int`. CLI `python3 scripts/verify_ci_gate.py` читає CI_PLAN_JSON, CI_NEEDS_JSON, GITHUB_SHA; exit 0 лише після всіх assertions.

- [ ] RED fixtures: needs=scope+8 IDs, result/outputs; scope outputs=plan JSON+8 boolean strings. `test_success`: required success, non-required success/skipped → [].
- [ ] RED `test_status_matrix`: кожен ID × failure/cancelled/skipped/neutral/timed_out/empty/null/missing; required лише success, non-required лише success/skipped. Scope не success, complete=false, repository=false → errors; push supply_chain=false → errors.
- [ ] RED `test_bad_output`: missing/extra IDs/keys, non-object, version=True або !=1, complete=1, required='false', absent outputs.plan, inconsistent scope outputs/plan → errors. CLI missing env/malformed JSON/stale tested_sha → exit 1 без traceback; correct → 0. Expected незалежні від evaluator.
- [ ] RED command: `python -m pytest scripts/tests/test_ci_gate.py -q -p no:cacheprovider`.
- [ ] Реалізація: fixed allowlist, exact schema/types/reasons/events/SHA; усі required results і outputs consistency. CLI tested_sha=GITHUB_SHA. Main-PR SBOM policy доводять classifier/workflow tests; evaluator перевіряє plan. Без network/files у evaluate, polling, catch-all success чи success fallback.
- [ ] GREEN: pytest вище; `python -m py_compile scripts/verify_ci_gate.py`; commit task files `ci: додати строгий gate`; review Task 3.

## Task 4: Атомарна міграція YAML

**Files:** ci.yml, 8 workflows із таблиці, `scripts/verify_ci_scopes.py`, `scripts/tests/test_ci_workflow_contract.py`. Monitor contract test адаптувати лише за необхідності без послаблення; live monitor не змінювати.
**Interfaces:** scope step ID plan, outputs plan+8 IDs; each call needs scope, `if: needs.scope.outputs.<ID> == 'true'`, exact local uses. Gate env CI_PLAN_JSON=`${{ needs.scope.outputs.plan }}`, CI_NEEDS_JSON=`${{ toJSON(needs) }}`. Verifier: `verify(root: Path) -> None`, `verify_workflow_contracts(root: Path) -> list[str]`, `main() -> int`; без import-time execution.

- [ ] RED `test_events` exact Global Constraints; `test_edited_reruns` без title/body/changes/action shortcuts; `test_graph` exact 10 jobs, uses, 9 gate needs, always(), timeout 2, unique name. `test_permissions_refs` exact read/pins/persist/ref, no secrets/inputs. `test_reusable_jobs` exact internal jobs, no job-level skip/continue-on-error, required steps не отримують новий error masking.
- [ ] RED `test_preservation`: negative shell assertions збережені; **не забороняти shell if/очікуваний nonzero**; SBOM cleanup step always() дозволений. Baseline YAML не містить continue-on-error; Android release checks перевіряють очікуваний nonzero через shell if + grep.
- [ ] RED mutations у tmp copy: missing needs/callee/SBOM job, job if/error masking, unpinned action, write permission → verifier errors. Existing live-monitor manual-only/offline monitor assertions pass.
- [ ] RED `test_concurrency_outputs`: group `ci-${{ github.event_name }}-${{ github.event.pull_request.number || github.run_id }}`; cancel-in-progress `${{ github.event_name == 'pull_request' }}`; унікальні main groups, Android old concurrency відсутня, exact output mappings. Command: `python -m pytest scripts/tests/test_ci_workflow_contract.py -q -p no:cacheprovider`.
- [ ] Створити ci.yml (name CI): scope timeout 5, gate 2, ubuntu-latest, stdlib Python >=3.12 без pip; невідповідний Python → failure. Checkout pin `3d3c42e5aac5ba805825da76410c181273ba90b1`, ref github.sha, persist=false; scope fetch-depth=0. Plan-file `$RUNNER_TEMP/ci-plan.json`. Upload pin `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a`, name `ci-plan-${{ github.sha }}-${{ github.run_id }}-${{ github.run_attempt }}`, retention 30, missing=error; upload failure → scope failure. Gate checkout/evaluator без skip shortcut.
- [ ] Вісім on-блоків → workflow_call:{}; explicit checkout ref; прибрати Android concurrency. Bodies/pins/timeouts/artifacts зберегти. Repository зберігає PyYAML/provenance/verifier; додати pytest==9.1.1 та 3 focused нові test files. Monitor pytest scripts/tests зберігається: дублювання малих tests можливе, автономних workflow runs немає.
- [ ] Verifier: зберегти 26 cases, 3 collector-runtime commands і всі supply-chain assertions; замінити лише старі SBOM trigger assertions на reusable/caller policy. Graph validation спільна для CLI/mutation tests. Success text: `26 examples passed` і `aggregate gate contract passed`.
- [ ] GREEN: `python -m pytest scripts/tests -q -p no:cacheprovider`; `python scripts/verify_ci_scopes.py`; `python scripts/verify_core_provenance.py`; `python scripts/verify_android.py`; `python -m ruff check scripts/ci_scopes.py scripts/verify_ci_gate.py scripts/verify_ci_scopes.py scripts/tests/test_ci_scopes.py scripts/tests/test_ci_gate.py scripts/tests/test_ci_workflow_contract.py`; `git diff --check`. Exit 0, pytest без failures, 26 cases/contracts passed.
- [ ] Schema: записати `actionlint -version`; `actionlint -shellcheck= -pyflakes= .github/workflows/*.yml` → exit 0. Missing tool: official pinned binary+checksum у test tooling, без product dependency. Semantic diff проти execution baseline: лише triggers/ref/concurrency/focused repository tests; heavy bodies/artifacts незмінні, live-monitor diff порожній.
- [ ] Один migration commit dispatcher+видалення старих triggers: `ci: об’єднати перевірки єдиним обов’язковим результатом`; exact stage task files; review Task 4. Не публікувати половину міграції.

## Task 5: Docs, один PR, приймання

**Files:** docs/MIGRATION.md, docs/MIGRATION-REMAINING.md, docs/RELEASE-READINESS.md.
**Interfaces:** reviewed Tasks 1–4; evidence одного run/attempt із head/base/tested SHA, results/artifacts.

- [ ] Docs: source/CI PR/CI main/enforcement окремо. Docs-only main PR усе ще repository+2 SBOM; edited title/body повторює потрібні jobs і витрачає бюджет без обходу failure. Protection/reviewer/bypass — окреме owner рішення; self-approval ikstv не незалежний review. Deployment/телефон/Play не закривати.
- [ ] `git diff --check`, `git diff --stat`, `git status --short`: task scope, чужі зміни збережено. Commit 3 docs `docs: описати єдиний CI-gate та межі захисту main`; review Task 5, потім whole-branch review. Виправити findings, повторити affected tests.
- [ ] Один push/PR до актуальної main після локального завершення; codex/ branch в ізоляції. Український body через structured tool/--body-file; attach PR app tool. Не повторювати локальні DB/Android suites без нового сигналу; workflow-edit PR дає один all-components run.
- [ ] Evidence: `gh pr checks <PR_NUMBER>`; `gh run view <RUN_ID> --json headSha,event,status,conclusion,jobs,url`; `gh api repos/ikstv/AvelRen-ORIGINAL/actions/runs/<RUN_ID>/artifacts --jq '.artifacts[] | {name,expired,size_in_bytes}'`. Перевірити gate success, усі 8 calls, source-sbom-<tested_sha>, runtime-image-sbom-<tested_sha>, ci-plan; expired=false. Plan/summary SHA відповідають цьому run, не лише PR head.
- [ ] Evidence: CLI exit codes success/failure/cancelled/required-skip/missing Task 3, mutations Task 4. Не ламати великий run: це локальні докази. Scheduler experiment — окремий малий план, без dispatcher bypass/fault inputs.
- [ ] Вартість — доступні billed usage/storage, не timeout/wall time. Budget block/pending/missing → CI не прийнято, $3 не збільшувати. Після окремо дозволеного merge перевірити main-push run; PR green його не замінює. Звіт: commit, tests, run URLs, межі доказів.

## Acceptance та відкладені рішення

Acceptance: Tasks 1–5 passed. Missing workflow/YAML error, conflict, fork approval, skip-ci, outage/cancellation не pass. PR YAML недовірений: без pull_request_target/privileged workflow_run.

Помилки до merge виправити у PR; після — revert без force-push. Втрата aggregate gate після revert документується.

Protection phase поза планом: окреме рішення тариф/модель, реальний reviewer, owner/admin bypass; effective API readback і failing-PR test merge identity ikstv до заяви enforcement. Billing/visibility/access/App/invitations не змінювати.

## Self-review — 12.10.2026

Coverage: scopes/diff → 1–2; gate → 3; YAML/SBOM → 4; docs/cost → 5. Interfaces/Review Focus перевірені. Лише читання й чернетка; source/tests/Git/Actions не виконувались.

Root запитує погодження плану; метод погоджено.

