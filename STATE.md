# AvelRen — state (generated automatically)

<!-- DO NOT EDIT BY HAND. This file is fully overwritten by
     scripts/generate-state.sh. Authorization boundaries live in AUTHORIZATION.md
     (this repo); detailed operational state lives in the private AvelRen-ops
     repo; only what is derived from git and gh lands here. -->

Generated from `main` @ `be8100e`.

## Prod vs. main

| | |
|---|---|
| Prod pinned to | `5b79d17` |
| `main` ahead by | **10 commit(s)** |

### What will ride into prod at the next Gate 11 re-prep

The Gate 11 atomicity rule binds evidence ↔ repo ↔ runner to a single commit, so
a re-prep carries **all** of these changes into prod together. The longer a
re-prep is deferred, the more unrelated changes ride into prod at the moment of
the riskiest operation. The list below is exactly that payload; if it is large,
consider splitting: first a re-prep and deploy without adoption, then a separate
one for 3B.2.

- `3a6314d` chore(deploy): pin prod to 5b79d17 after installing the snapshot script (#166)
- `ae4cb4d` ci: let the state workflow start the checks its own PR cannot (#159) (#167)
- `ca1f60d` chore(state): regenerate STATE.md (#162)
- `4660b8f` ci(state): bring the reused branch up to date, or the PR still cannot merge (#168)
- `3b6c916` chore(state): regenerate STATE.md (#169)
- `5b45e3e` Revert "ci: let the state workflow start the checks its own PR cannot (#159)" (#170)
- `ed90ffe` chore(state): regenerate STATE.md (#171)
- `21e5ad9` feat(supply-chain): hash-pinned dependency lock for the runtime image (#23) (#172)
- `beda7ea` feat(health): external gate for alerts that fire and reach nobody (#174) (#175)
- `be8100e` feat(supply-chain): lock the Gradle dependency graph (#23) (#176)

Of these, touching the live runtime (`app/`, `db/`, `deploy/`, compose): **3**.

> ⚠ `app/Dockerfile` changed — the runtime base image. Currently:
> `FROM python:3.14-slim`.
> A language-version bump of the live image deserves its own window, not one
> combined with adoption.

## Open PRs and issues

### PRs

- #173 chore(state): regenerate STATE.md — `chore/state-refresh`
- #143 chore(deps): bump the compose-images group across 1 directory with 2 updates — `dependabot/docker_compose/compose-images-df86d7246b`
- #140 chore(deps): bump the actions group across 1 directory with 3 updates — `dependabot/github_actions/actions-821e0a5e16`
- #138 chore(deps): bump python from `ce40764` to `cad9a2c` in /app — `dependabot/docker/app/python-cae66f2`
- #137 feat(app): truthful server-status badge for all users — `feat/truthful-server-badge`
- #123 docs: "a signal has a date" — three staleness rules — `docs/signal-has-a-date`

### Issues

- #174 Перереєстрація застосунку осиротює підписки — 5 з 6 порогових тривог не доставлено, і цього не видно ні клієнту, ні серверу
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
| `chore/repo-tidy` | 2 | 35 |
| `chore/state-refresh` | 3 | 1 |
| `dependabot/docker/app/python-cae66f2` | 1 | 2 |
| `dependabot/docker_compose/compose-images-df86d7246b` | 1 | 19 |
| `dependabot/github_actions/actions-821e0a5e16` | 1 | 1 |
| `docs/readme-professional` | 1 | 90 |
| `docs/signal-has-a-date` | 1 | 39 |
| `feat/launcher-road-a` | 1 | 32 |
| `feat/privacy-page` | 3 | 34 |
| `feat/truthful-server-badge` | 1 | 29 |
| `fix/backup-grants-and-rate-limits` | 1 | 26 |
