# AvelRen — state (generated automatically)

<!-- DO NOT EDIT BY HAND. This file is fully overwritten by
     scripts/generate-state.sh. Authorization boundaries live in AUTHORIZATION.md
     (this repo); detailed operational state lives in the private AvelRen-ops
     repo; only what is derived from git and gh lands here. -->

Generated from `main` @ `3b9c042`.

## Prod vs. main

| | |
|---|---|
| Prod pinned to | `ebce449` |
| `main` ahead by | **22 commit(s)** |

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
- `6828dec` feat(health): external gate for an empty watchdog alert channel (#113) (#129)
- `f2b300e` fix(eta,api): a zero wait with cars queued is no estimate, not "enter now" (#149)
- `108bfac` fix(api): serve /history from clean hourly buckets, not the contaminated aggregate (#151)
- `8a91095` feat(android): warn when a granted permission still cannot wake the driver (#117) (#150)
- `f46d5e1` fix(ci,compose): probe database readiness over TCP, the transport clients use (#146) (#153)
- `39ee23a` feat(ops): a supported way to mark a device admin, instead of a hand UPDATE (#112) (#155)
- `7ba9692` docs(readme): badges, a documentation index, and an architecture diagram (#119) (#152)
- `3b9c042` ci: audit the resolved Python dependency set against known advisories (#23) (#156)

Of these, touching the live runtime (`app/`, `db/`, `deploy/`, compose): **14**.

## Open PRs and issues

### PRs

- #157 chore(state): regenerate STATE.md — `chore/state-refresh`
- #154 chore(state): regenerate STATE.md and unblock the red run on main — `chore/state-refresh-live`
- #148 fix(backup): persist rclone's refreshed OAuth token (issue #121) — `fix/backup-rclone-token-write`
- #143 chore(deps): bump the compose-images group across 1 directory with 2 updates — `dependabot/docker_compose/compose-images-df86d7246b`
- #140 chore(deps): bump the actions group across 1 directory with 3 updates — `dependabot/github_actions/actions-821e0a5e16`
- #138 chore(deps): bump python from `ce40764` to `cae66f2` in /app — `dependabot/docker/app/python-cae66f2`
- #137 feat(app): truthful server-status badge for all users — `feat/truthful-server-badge`
- #123 docs: "a signal has a date" — three staleness rules — `docs/signal-has-a-date`

### Issues

- #158 🔴 external monitor: watchdog alert channel is blind
- #146 backend-tests: кроки, що залежать від готовності БД, не чекають на неї (флейк startup-гонки)
- #127 ETA несе ту саму контамінацію, що й forecast — eta.py фільтрує лише is_paused
- #121 backup: rclone не зберігає оновлений токен (ProtectHome=read-only) — перенести конфіг у /etc/avelren
- #119 README: port badges + docs-index + (redraw) architecture diagram onto English README
- #117 Відсутній дозвіл на сповіщення робить застосунок беззвучним — ні користувач, ні сервер цього не бачать
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
| `chore/repo-tidy` | 2 | 19 |
| `chore/state-refresh` | 12 | 11 |
| `chore/state-refresh-live` | 3 | 0 |
| `dependabot/docker/app/python-cae66f2` | 1 | 13 |
| `dependabot/docker_compose/compose-images-df86d7246b` | 1 | 3 |
| `dependabot/github_actions/actions-821e0a5e16` | 1 | 2 |
| `docs/readme-professional` | 1 | 74 |
| `docs/signal-has-a-date` | 1 | 23 |
| `feat/launcher-road-a` | 1 | 16 |
| `feat/privacy-page` | 3 | 18 |
| `feat/truthful-server-badge` | 1 | 13 |
| `fix/backup-grants-and-rate-limits` | 1 | 10 |
| `fix/backup-rclone-token-write` | 2 | 9 |
