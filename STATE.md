# AvelRen — стан (генерується автоматично)

<!-- НЕ РЕДАГУВАТИ РУКАМИ. Файл повністю перезаписується
     scripts/generate-state.sh. Політика і межі авторизації живуть у
     PROJECT_STATUS.md; сюди потрапляє тільки те, що виводиться з git та gh. -->

Згенеровано з `main` @ `9400a8d`.

## Прод проти main

| | |
|---|---|
| Прод запінено на | `8b8eed2` |
| `main` попереду на | **22 коміт(ів)** |

### Що заїде в прод при наступному Gate 11 re-prep

Правило атомарності Gate 11 привʼязує evidence ↔ repo ↔ runner до одного
коміта, тож re-prep везе в прод **усі** ці зміни разом. Що довше re-prep
відкладається, то більше стороннього їде в прод у момент найризикованішої
операції. Список нижче — саме той вантаж; якщо він великий, розгляньте
розчеплення: спершу re-prep і деплой без adoption, потім окремий під 3B.2.

- `a70bb60` chore(ci): add Dependabot and CodeQL supply-chain gates (#64)
- `f5333b7` fix(telemetry): completeness counts successful cycles, not attempts (#63)
- `86aab16` fix(ci): split Dependabot major updates from routine bumps (#69)
- `ee707b8` fix(adoption): let the privilege gate actually run on production (#68)
- `706598d` fix(compose): pass eCherha device identity into the collector (#70)
- `f6fe509` ci: enforce that the mobile app never calls eCherha directly (#72)
- `f2cbcfc` chore(ci): park Android version bumps in Dependabot until #18 migration (#73)
- `36dfd3c` chore(compose): pin external image digests for reproducible builds (#74)
- `1948d76` chore: gitignore the operational docker-compose.override.yml (#75)
- `eacba0c` feat(android): Modernist theme (light/dark + toggle) and onboarding (#60)
- `fc34621` chore(deps): bump gradle/actions/setup-gradle (#77)
- `10936d4` chore(audit): close F6/F7 and the SBOM half of F4 (#81)
- `92258b2` fix(watchdog): read host facts from telemetry snapshot, drop broad /run mount (T-06, M-1) (#54)
- `fd37148` chore(deps): bump the actions-major group across 1 directory with 6 updates (#79)
- `fdfd0aa` feat(ci): independent black-box health monitor (F8, #22) (#82)
- `03eb343` fix(ci): stub google-services.json only when absent, never clobber real one (#83)
- `52d32b0` chore(docker): pin python base image by digest (issue #23) (#85)
- `984fdb3` feat(android): surface the real cause when Installation goes Unavailable (#84)
- `4758b4f` fix(adoption): restart the runtime on the legacy DSN after a rollback (F1/F2) (#80)
- `6df5e4e` fix(caddy): cap /api request body at 64KB + wire caddy validate in CI (T-05, M-2) (#53)
- `3d9c02d` docs(audit): full project audit 2026-08-15 (#78)
- `9400a8d` chore(deps): bump python (#65)

З них зачіпають бойовий рантайм (`app/`, `db/`, `deploy/`, compose): **9**.

> ⚠ Змінився `app/Dockerfile` — базовий образ рантайму. Зараз:
> `FROM python:3.14-slim`.
> Стрибок версії мови на бойовому образі заслуговує окремого вікна, не
> суміщеного з adoption.

## Відкриті PR та issues

### PR

- #55 docs(readme): professional rewrite — badges, mermaid, docs index _(draft)_ — `docs/readme-professional`
- #52 feat(android): migrate to API 36 (T-03, #18) _(draft)_ — `feat/android-api36-t03`

### Issues

- #26 audit: Production hardening після аудиту 7e110306 / Production hardening after the 7e110306 audit
- #25 docs: Privacy, retention і release runbooks / Privacy, retention, and release runbooks
- #23 chore: Відтворювані builds і supply-chain gates / Reproducible builds and supply-chain gates
- #19 security: Володіння FCM token і retention installations / Enforce FCM token ownership and installation retention
- #18 chore: Міграція Android на API 36 / Migrate Android to API 36
- #15 security: Розділення PostgreSQL runtime roles / Split PostgreSQL runtime roles

## Гілки на origin проти main

| Гілка | Попереду | Позаду |
|---|---|---|
| `dependabot/docker/app/backend-images-6dafb4a59b` | 2 | 1 |
| `docs/readme-professional` | 1 | 29 |
| `feat/android-api36-t03` | 1 | 29 |
