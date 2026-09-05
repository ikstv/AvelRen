# AvelRen — state (generated automatically)

<!-- DO NOT EDIT BY HAND. This file is fully overwritten by
     scripts/generate-state.sh. Authorization boundaries live in AUTHORIZATION.md
     (this repo); detailed operational state lives in the private AvelRen-ops
     repo; only what is derived from git and gh lands here. -->

Generated from `main` @ `b50fc8e`.

## Prod vs. main

| | |
|---|---|
| Prod pinned to | `6df3610` |
| `main` ahead by | **2 commit(s)** |

### What will ride into prod at the next Gate 11 re-prep

The Gate 11 atomicity rule binds evidence ↔ repo ↔ runner to a single commit, so
a re-prep carries **all** of these changes into prod together. The longer a
re-prep is deferred, the more unrelated changes ride into prod at the moment of
the riskiest operation. The list below is exactly that payload; if it is large,
consider splitting: first a re-prep and deploy without adoption, then a separate
one for 3B.2.

- `59077b6` chore(deploy): pin prod to 6df3610 after the 2026-09-05 deploy (#161)
- `b50fc8e` feat(telemetry,watchdog): watch the migration pin between deploy windows (#160) (#163)

Of these, touching the live runtime (`app/`, `db/`, `deploy/`, compose): **2**.

## Open PRs and issues

### PRs

- #162 chore(state): regenerate STATE.md — `chore/state-refresh`
- #143 chore(deps): bump the compose-images group across 1 directory with 2 updates — `dependabot/docker_compose/compose-images-df86d7246b`
- #140 chore(deps): bump the actions group across 1 directory with 3 updates — `dependabot/github_actions/actions-821e0a5e16`
- #138 chore(deps): bump python from `ce40764` to `cae66f2` in /app — `dependabot/docker/app/python-cae66f2`
- #137 feat(app): truthful server-status badge for all users — `feat/truthful-server-badge`
- #123 docs: "a signal has a date" — three staleness rules — `docs/signal-has-a-date`

### Issues

- #160 prod: міграційний пін 009 випав з активного override — /migrations монтується з репозиторію
- #159 state workflow: the PR it opens can never be merged (GITHUB_TOKEN starts no checks)
- #121 backup: rclone не зберігає оновлений токен (ProtectHome=read-only) — перенести конфіг у /etc/avelren
- #117 Відсутній дозвіл на сповіщення робить застосунок беззвучним — ні користувач, ні сервер цього не бачать
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
| `chore/repo-tidy` | 2 | 24 |
| `chore/state-refresh` | 1 | 1 |
| `dependabot/docker/app/python-cae66f2` | 1 | 18 |
| `dependabot/docker_compose/compose-images-df86d7246b` | 1 | 8 |
| `dependabot/github_actions/actions-821e0a5e16` | 1 | 7 |
| `docs/readme-professional` | 1 | 79 |
| `docs/signal-has-a-date` | 1 | 28 |
| `feat/launcher-road-a` | 1 | 21 |
| `feat/privacy-page` | 3 | 23 |
| `feat/truthful-server-badge` | 1 | 18 |
| `fix/backup-grants-and-rate-limits` | 1 | 15 |
