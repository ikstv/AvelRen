# AvelRen — state (generated automatically)

<!-- DO NOT EDIT BY HAND. This file is fully overwritten by
     scripts/generate-state.sh. Authorization boundaries live in AUTHORIZATION.md
     (this repo); detailed operational state lives in the private AvelRen-ops
     repo; only what is derived from git and gh lands here. -->

Generated from `main` @ `73a8d14`.

## Prod vs. main

| | |
|---|---|
| Prod pinned to | `ebce449` |
| `main` ahead by | **14 commit(s)** |

### What will ride into prod at the next Gate 11 re-prep

The Gate 11 atomicity rule binds evidence ↔ repo ↔ runner to a single commit, so
a re-prep carries **all** of these changes into prod together. The longer a
re-prep is deferred, the more unrelated changes ride into prod at the moment of
the riskiest operation. The list below is exactly that payload; if it is large,
consider splitting: first a re-prep and deploy without adoption, then a separate
one for 3B.2.

- `ecbf5b0` chore(deploy): pin prod to ebce449 after the #88 window (#125)
- `fe0ee5e` fix(forecast): drop wait=0∧vehicles>0 contamination from the baseline (#111) (#126)
- `9663654` feat(android): release signing config + staged R8 rules (#25) (#130)
- `1f4ea63` chore(repo): move audit artifacts under docs/audits/, ignore _architect/ (#131)
- `4e258ab` feat(deploy): static privacy policy at /privacy (#132)
- `bf0982e` feat(onboarding): beta notice + privacy policy on the first screen (#133)
- `5c4fcbc` feat(launcher): Road-A adaptive icon (yellow A + road), replaces bell (#134)
- `8ab1b57` chore(repo): split ops into private AvelRen-ops + neutralize public prose (A + B1) (#135)
- `ac19251` fix(android): replace onboarding background, add asset provenance gate (#136)
- `b9caa61` feat(app): source attribution for єЧerha data (Play Misleading Claims) (#139)
- `6b89275` fix(ci): three gates that were failing silently, or not running at all (#142)
- `2e38364` fix(api,tests): full rate-limit coverage + app suite under least-privilege role (#145)
- `aaa0838` fix(backup,ci): keep future objects backup-readable without a migration (#144) (#147)
- `73a8d14` fix(collector): never record an empty collector_runs.error (#91) (#128)

Of these, touching the live runtime (`app/`, `db/`, `deploy/`, compose): **9**.

## Open PRs and issues

### PRs

- #156 ci: audit the resolved Python dependency set against known advisories (#23) — `ci/dependency-audit-23`
- #155 feat(ops): a supported way to mark a device admin, instead of a hand UPDATE (#112) — `feat/admin-enroll-112`
- #154 chore(state): regenerate STATE.md and unblock the red run on main — `chore/state-refresh-live`
- #153 fix(ci,compose): probe database readiness over TCP, the transport clients use (#146) — `fix/db-readiness-tcp-probe-146`
- #152 docs(readme): badges, a documentation index, and an architecture diagram (#119) — `docs/readme-badges-index-diagram-119`
- #151 fix(api): serve /history from clean hourly buckets, not the contaminated aggregate (#111) — `fix/history-clean-hourly-111`
- #150 feat(android): warn when a granted permission still cannot wake the driver (#117) — `fix/background-delivery-hint-117`
- #149 fix(eta,api): a zero wait with cars queued is no estimate, not "enter now" (#127) — `fix/eta-contamination-127`
- #148 fix(backup): persist rclone's refreshed OAuth token (issue #121) — `fix/backup-rclone-token-write`
- #143 chore(deps): bump the compose-images group with 2 updates — `dependabot/docker_compose/compose-images-df86d7246b`
- #140 chore(deps): bump the actions group across 1 directory with 3 updates — `dependabot/github_actions/actions-821e0a5e16`
- #138 chore(deps): bump python from `ce40764` to `cae66f2` in /app — `dependabot/docker/app/python-cae66f2`
- #137 feat(app): truthful server-status badge for all users — `feat/truthful-server-badge`
- #129 feat(health): external gate for an empty watchdog alert channel (#113) — `fix/alert-channel-gate-113`
- #123 docs: "a signal has a date" — three staleness rules — `docs/signal-has-a-date`

### Issues

- #146 backend-tests: кроки, що залежать від готовності БД, не чекають на неї (флейк startup-гонки)
- #127 ETA несе ту саму контамінацію, що й forecast — eta.py фільтрує лише is_paused
- #121 backup: rclone не зберігає оновлений токен (ProtectHome=read-only) — перенести конфіг у /etc/avelren
- #119 README: port badges + docs-index + (redraw) architecture diagram onto English README
- #117 Відсутній дозвіл на сповіщення робить застосунок беззвучним — ні користувач, ні сервер цього не бачать
- #113 Ніщо не перевіряє, що канал алертів watchdog непорожній
- #112 Немає способу призначити is_admin, окрім ручного UPDATE devices — канал алертів висихає тихо
- #111 forecast/ETA занижують очікування: відсутні оцінки пишуться як wait=0 (обхід дійсний до 2026-10-29)
- #110 Робота на двох ПК (десктоп + ноутбук): доступи, синхрон, стан дошки
- #26 audit: Production hardening після аудиту 7e110306 / Production hardening after the 7e110306 audit
- #25 docs: Privacy, retention і release runbooks / Privacy, retention, and release runbooks
- #23 chore: Відтворювані builds і supply-chain gates / Reproducible builds and supply-chain gates
- #19 security: Володіння FCM token і retention installations / Enforce FCM token ownership and installation retention
- #15 security: Розділення PostgreSQL runtime roles / Split PostgreSQL runtime roles

## Branches on origin vs. main

| Branch | Ahead | Behind |
|---|---|---|
| `chore/repo-tidy` | 2 | 11 |
| `chore/state-refresh` | 3 | 3 |
| `chore/state-refresh-live` | 1 | 1 |
| `ci/dependency-audit-23` | 1 | 1 |
| `dependabot/docker/app/python-cae66f2` | 1 | 5 |
| `dependabot/docker_compose/compose-images-df86d7246b` | 1 | 3 |
| `dependabot/github_actions/actions-821e0a5e16` | 1 | 1 |
| `docs/readme-badges-index-diagram-119` | 1 | 1 |
| `docs/readme-professional` | 1 | 66 |
| `docs/signal-has-a-date` | 1 | 15 |
| `feat/admin-enroll-112` | 2 | 1 |
| `feat/launcher-road-a` | 1 | 8 |
| `feat/privacy-page` | 3 | 10 |
| `feat/truthful-server-badge` | 1 | 5 |
| `fix/alert-channel-gate-113` | 2 | 1 |
| `fix/background-delivery-hint-117` | 1 | 1 |
| `fix/backup-grants-and-rate-limits` | 1 | 2 |
| `fix/backup-rclone-token-write` | 2 | 1 |
| `fix/db-readiness-tcp-probe-146` | 1 | 1 |
| `fix/eta-contamination-127` | 1 | 1 |
| `fix/history-clean-hourly-111` | 1 | 1 |
