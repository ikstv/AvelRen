# AvelRen — state (generated automatically)

<!-- DO NOT EDIT BY HAND. This file is fully overwritten by
     scripts/generate-state.sh. Authorization boundaries live in AUTHORIZATION.md
     (this repo); detailed operational state lives in the private AvelRen-ops
     repo; only what is derived from git and gh lands here. -->

Generated from `main` @ `6b89275`.

## Prod vs. main

| | |
|---|---|
| Prod pinned to | `ebce449` |
| `main` ahead by | **11 commit(s)** |

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

Of these, touching the live runtime (`app/`, `db/`, `deploy/`, compose): **6**.

## Open PRs and issues

### PRs

- #141 fix(db,api): backup grants for future objects, full rate-limit coverage — `fix/backup-grants-and-rate-limits`
- #140 chore(deps): bump the actions group across 1 directory with 3 updates — `dependabot/github_actions/actions-821e0a5e16`
- #138 chore(deps): bump python from `ce40764` to `cae66f2` in /app — `dependabot/docker/app/python-cae66f2`
- #137 feat(app): truthful server-status badge for all users — `feat/truthful-server-badge`
- #129 feat(health): external gate for an empty watchdog alert channel (#113) — `fix/alert-channel-gate-113`
- #128 fix(collector): never record an empty collector_runs.error (#91) — `fix/collector-runs-error-91`
- #123 docs: "a signal has a date" — three staleness rules — `docs/signal-has-a-date`

### Issues

- #127 ETA несе ту саму контамінацію, що й forecast — eta.py фільтрує лише is_paused
- #122 host: плановий ребут для активації ядра 6.8.0-138 (працює 6.8.0-137)
- #121 backup: rclone не зберігає оновлений токен (ProtectHome=read-only) — перенести конфіг у /etc/avelren
- #119 README: port badges + docs-index + (redraw) architecture diagram onto English README
- #117 Відсутній дозвіл на сповіщення робить застосунок беззвучним — ні користувач, ні сервер цього не бачать
- #114 collector_runs.derived_error — NULL у 100% рядків: мертвий або зламаний шлях запису
- #113 Ніщо не перевіряє, що канал алертів watchdog непорожній
- #112 Немає способу призначити is_admin, окрім ручного UPDATE devices — канал алертів висихає тихо
- #111 forecast/ETA занижують очікування: відсутні оцінки пишуться як wait=0 (обхід дійсний до 2026-10-29)
- #110 Робота на двох ПК (десктоп + ноутбук): доступи, синхрон, стан дошки
- #91 collector_runs.error записує порожній рядок замість причини збою
- #26 audit: Production hardening після аудиту 7e110306 / Production hardening after the 7e110306 audit
- #25 docs: Privacy, retention і release runbooks / Privacy, retention, and release runbooks
- #23 chore: Відтворювані builds і supply-chain gates / Reproducible builds and supply-chain gates
- #19 security: Володіння FCM token і retention installations / Enforce FCM token ownership and installation retention
- #15 security: Розділення PostgreSQL runtime roles / Split PostgreSQL runtime roles

## Branches on origin vs. main

| Branch | Ahead | Behind |
|---|---|---|
| `chore/repo-tidy` | 2 | 8 |
| `dependabot/docker/app/python-cae66f2` | 1 | 2 |
| `dependabot/github_actions/actions-821e0a5e16` | 1 | 1 |
| `docs/readme-professional` | 1 | 63 |
| `docs/signal-has-a-date` | 1 | 12 |
| `feat/launcher-road-a` | 1 | 5 |
| `feat/privacy-page` | 3 | 7 |
| `feat/truthful-server-badge` | 1 | 2 |
| `fix/alert-channel-gate-113` | 1 | 9 |
| `fix/backup-grants-and-rate-limits` | 1 | 1 |
| `fix/collector-runs-error-91` | 1 | 9 |
