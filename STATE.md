# AvelRen — state (generated automatically)

<!-- DO NOT EDIT BY HAND. This file is fully overwritten by
     scripts/generate-state.sh. Authorization boundaries live in AUTHORIZATION.md
     (this repo); detailed operational state lives in the private AvelRen-ops
     repo; only what is derived from git and gh lands here. -->

Generated from `main` @ `4a8e010`.

## Prod vs. main

| | |
|---|---|
| Prod pinned to | `254fd17` |
| `main` ahead by | **6 commit(s)** |

### What will ride into prod at the next Gate 11 re-prep

The Gate 11 atomicity rule binds evidence ↔ repo ↔ runner to a single commit, so
a re-prep carries **all** of these changes into prod together. The longer a
re-prep is deferred, the more unrelated changes ride into prod at the moment of
the riskiest operation. The list below is exactly that payload; if it is large,
consider splitting: first a re-prep and deploy without adoption, then a separate
one for 3B.2.

- `fb89075` chore(deploy): pin prod to 254fd17 after the silent-device deploy (#181)
- `dfcde7a` Clarify onboarding Premium and source copy (#189)
- `b766b2f` Show Google Play in-app update prompt (#191)
- `676a9f4` Refine settings and onboarding copy (#192)
- `661b744` Polish update prompt and settings footer (#193)
- `4a8e010` Адміністрування та підготовка релізу 0.1.1 (#194)

Of these, touching the live runtime (`app/`, `db/`, `deploy/`, compose): **2**.

## Open PRs and issues

### PRs

- #190 Expire inactive device data after 90 days — `codex/device-retention-cleanup`
- #188 Sync production daily status and telemetry cleanup — `fix/prod-observability-cleanup`
- #185 Fix forecast quality evaluation — `codex/held-out-forecast`
- #184 Explain upcoming Premium features — `codex/premium-instructions`
- #183 Automate inactive-device retention — `codex/fix-launcher-icon`
- #173 chore(state): regenerate STATE.md — `chore/state-refresh`
- #143 chore(deps): bump the compose-images group across 1 directory with 2 updates — `dependabot/docker_compose/compose-images-df86d7246b`
- #140 chore(deps): bump the actions group across 1 directory with 3 updates — `dependabot/github_actions/actions-821e0a5e16`
- #138 chore(deps): bump python from `ce40764` to `cad9a2c` in /app — `dependabot/docker/app/python-cae66f2`
- #137 feat(app): truthful server-status badge for all users — `feat/truthful-server-badge`
- #123 docs: "a signal has a date" — three staleness rules — `docs/signal-has-a-date`

### Issues

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
| `chore/repo-tidy` | 2 | 44 |
| `chore/state-refresh` | 41 | 0 |
| `codex/admin-access` | 5 | 1 |
| `codex/device-retention-cleanup` | 2 | 5 |
| `codex/fix-launcher-icon` | 6 | 5 |
| `codex/held-out-forecast` | 13 | 5 |
| `codex/premium-instructions` | 7 | 5 |
| `dependabot/docker/app/python-cae66f2` | 1 | 11 |
| `dependabot/docker_compose/compose-images-df86d7246b` | 1 | 5 |
| `dependabot/github_actions/actions-821e0a5e16` | 1 | 0 |
| `docs/readme-professional` | 1 | 99 |
| `docs/signal-has-a-date` | 1 | 48 |
| `feat/launcher-road-a` | 1 | 41 |
| `feat/privacy-page` | 3 | 43 |
| `feat/truthful-server-badge` | 1 | 38 |
| `fix/backup-grants-and-rate-limits` | 1 | 35 |
| `fix/prod-observability-cleanup` | 4 | 5 |
