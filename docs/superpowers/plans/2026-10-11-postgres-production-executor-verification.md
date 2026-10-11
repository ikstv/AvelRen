# Перевірка PostgreSQL production executor — 2026-10-11

Вихідний механізм першого етапу реалізований. Production CLI закритий; maintenance adapter, DSN cutover та приймання робочого сервера залишаються окремими етапами.

Шість задач пройшли окремі незалежні перегляди. Загальний перегляд виявив race між forward acceptance та inverse; його виправлено комітом `0eefe85c7dad03ddfeedb4cfa2aa7e21f3a8a7f5`. Окремий повторний перегляд підтвердив усунення без нових Critical/Important findings.

Фінальні локальні докази:

- 669 backend unit tests PASS після CI fixture fix; 81 focused preflight/production/transaction unit tests PASS, включно з explicit active-autovacuum refusal. Попередні 668/56 стосувалися lifecycle fix.
- 86 повних adoption DB tests PASS до lifecycle fix; після fix 72 affected DB tests PASS, включно з конкуренцією apply/inverse. Це історичні перевірки до наступного CI integration fix. Production guard зберігає відмову для активного autovacuum; database/adoption isolated fixtures використовують однаковий autovacuum=off overlay.
- Після CI fixture fix точний default виклик `bash scripts/test_database.sh` — 176 tests PASS за 584.04s, без зміни набору tests. Hosted run 38153642492 перед цим мав 175 PASS / 1 FAIL у initial apply setup evidence-drift test; category не логувалася. Diagnostic default rerun до fix дав 176 PASS за 577.03s, тому конкретна причина hosted rollback не доведена. Виправлено підтверджену різницю fixture configuration, а assertions тепер зберігають весь AdoptionResult.
- Після окремого upgrade fixture fix `bash ops/timescale-upgrade-test.sh` — 262 PASS, 1 наявний API performance SKIP, 2 baseline warnings за 719.85s; pipeline exit 0. Обидва old/new startup SHOW assertions, upgrade 2.17.2→2.30.1, compressed backup/restore, дані/journal/schema/API/collector contracts PASS. Hosted run 38157674874 раніше мав 261 PASS / 1 FAIL / 1 SKIP з category active_sessions; конкретного peer log не зберіг. Production source/unit tests не змінені, тож 669/81 unit proof не повторювався.
- Двокластерна репетиція PASS: однакові catalog/plan та journal 001–016, інший system identifier відхилений; обидві БД незмінні.
- Restore/adoption/inverse репетиція PASS: дані, journal та обмежені права перевірені.
- Ruff, CI scopes (26 examples), provenance (CORE19/DB14/API17/WATCHDOG3), shell syntax та diff PASS.
- Усі ресурси власних fixture projects очищені. Жодних змін робочого сервера, міграцій/bootstrap або upstream probes.

Команди: cached Linux Python image `python -m pytest -c services/backend/pytest.ini services/backend/tests/unit -q -p no:cacheprovider`; `bash scripts/test_database.sh adoption`; affected selector `adoption_production or adoption_mutation or adoption_inverse`; `bash ops/postgres-production-adoption-test.sh`; `bash ops/postgres-adoption-restore-test.sh`; `ruff check services/backend/src services/backend/tests scripts/*.py`; `python scripts/verify_ci_scopes.py`; `python scripts/verify_core_provenance.py`; `git diff --check`.

Відомі попередні warnings: Starlette/httpx, anyio BlockingPortal, bootstrap role membership та pg_dump CAGG circular FK. Вони не приховуються. Hosted exact-head CI — окремий integration gate; локальні результати не є deployment.

## Entry points production quiescence tests

Інвентаризація tracked shell/Python/workflow та інших launchers від 11.10.2026:

| Entry point | Набір | Налаштування fixture |
|---|---|---|
| `scripts/test_database.sh` / `database` | 176 root DB cases без API/watchdog | database/adoption overlay, autovacuum=off |
| `scripts/test_database.sh adoption` | Adoption subset, включно з production module | Той самий overlay |
| `ops/timescale-upgrade-test.sh` | Весь DB/API/watchdog tree після upgrade, 263 cases | Окремий owned upgrade compose, autovacuum=off і SHOW після обох startups |

API/watchdog/surge profiles не збирають production module й не змінені. Two-cluster
rehearsal імпортує лише helpers та відмовляє target_mismatch до quiescence;
restore/adoption rehearsal виконує explicit disposable contracts. Default CMD
`Dockerfile.database-test` указує весь DB tree, але tracked runners завжди
передають explicit command; додаткових implicit-CMD запусків не знайдено.
Natural autovacuum scheduling у database/adoption/upgrade fixtures не тестується;
production guard та його explicit active-autovacuum refusal unit test незмінні.

## Рішення координатора та ризик помилки

- Task 2 Ruling: verified checkout-root provenance belongs to RuntimeVerifier; evidence helper checks nonempty absolute existing non-aliased roots and exclusion, without Git-marker trust inference — follows spec adapter boundary — if wrong, location API must change before adapter integration.
- Task 2 Ruling: current intent/committed/accepted and inverse receipt phases require category None; failures remain AdoptionResult diagnostics, not accepted receipts — prevents failure records implying acceptance — if future failure receipt phases are needed, add explicit schema then.
- Task 2 Ruling: operation manifest gets exclusive production-operation.sha256 sidecar via existing private I/O — required checksum-tampering detection with unchanged flat format1 — extra file can leave incomplete evidence on publication failure, deliberately blocks resume.
- Task 3 Ruling: allow only exact idle TimescaleDB Background Worker Scheduler by backend_type + application_name + idle state when every job proven Paused; all other peers/unknown metadata refuse — scheduler is a verified non-application-writer and cannot be removed by pausing jobs — if classification changes, helper must refuse and adapter/allowlist needs pinned revalidation.
- Task 3 Ruling: acquire_adoption_locks is locks-only; production require_quiescent is explicit post-lock callback (task5); task3 lock-wait test composes both — shared task4 must preserve disposable behavior without production-only job gates — if wiring omits callback, production could miss sessions; task5 integration tests must prove it.
- Task4 Ruling: engine statuses committed/rolled_back/rollback_failed/commit_unknown; verified rollback retains AdoptionError category, failed proof pre_commit_unverified, ack loss commit_acknowledgement_unavailable. Disposable adapter may re-raise original pre-write rejection only after verified rollback/close, never masking unknown/failed rollback — preserves old CLI semantics and explicit engine outcomes — if wrong, Task5 mapping and adapter tests must change before integration.
- Task4 Ruling: before any mutation statement attempt, locked drift/callback failure is a zero-mutation refusal: confirmed rollback and close then categorical AdoptionError, no plan.from proof of foreign drift. Failed rollback/close remains rollback_failed. After first attempted mutation, separate read-only from proof mandatory — preserves foreign ACL changes and old refusal behavior without treating foreign drift as our failed rollback — if wrong, consumers need a distinct refused outcome instead of exception. Tests required for zero-write callback/drift preservation and refusal rollback failure.
- Task4 Ruling: disposable during_inverse failpoint moves to before_commit after inverse SQL; category/result and rollback durable target preserved, no shared engine test-env hooks — exact first-statement timing is internal and existing observable atomicity is binding — if timing matters to uncovered tests, add a callback boundary or revise test harness without production bypass.
- Task6 Ruling: initialize synthetic journal applied_at to fixed UTC instant in both freshly migrated owned fixture DBs before baseline; retain exact fingerprint/plan equality and assert entire journal unchanged through refusal — independently run migrations naturally timestamp differently and test needs identical catalogs — if applied to real restore artifacts this would falsify evidence, so fixture-only setup and explicit provenance required; production inventory and migration SQL remain unchanged.
- Final Ruling: production-only fixed postgres maintenance-DB guard on same DSN server/credentials, verified cluster/sessionrole/targetdbname+OID, identity-derived nonblocking advisory lock held through final receipt; competing applies/inverse refusebusy before mutation. Targetquiescence unchanged because guard outside target. Guardownership/liveness checked before publication; postpossiblecommit uncertainty unknown. No alternate/fallback lock DB — closes confirmed lifecycle race across distinct evidence dirs — costifwrong: deployment requires additional CONNECT/controlidentity read and permission/provenance revalidation; actualadapter must satisfy documented prerequisite, CLI staysclosed.
- Final Ruling, уточнено після hosted CI: database/adoption/upgrade disposable fixture servers autovacuum=off, scoped owned ephemeral harness only; всі три entrypoints збирають production quiescence cases. Це вузько замінює попередні adoption-only та database/adoption scopes; окремі API/watchdog/surge profiles і production unchanged. Попередня exact refusal metadata active autovacuum worker довела правильність production guard, але hosted failures без peer metadata окремо не доводять цього peer. Початковий settle не може запобігти пізнішому vacuum; ці fixtures більше не перевіряють natural vacuum scheduling. Explicit active-autovacuum refusal unit test та actual maintenance мають враховувати його, ніколи не allowlist.
