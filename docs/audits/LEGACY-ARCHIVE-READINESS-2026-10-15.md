# Повторна звірка старих репозиторіїв перед архівацією — 15.10.2026

Це read-only інвентаризація перед майбутнім архівуванням, а не дозвіл на
видалення. Вона виконана після злиття PR #144 у `AvelRen-ORIGINAL` як
`8fdb9c245dd57aa62c050659fd90888ead836bec`. Сервер, старі репозиторії,
issues, PR, workflows і налаштування доступу не змінювалися.

## Знімок джерел

| Репозиторій | Видимість | Main | Гілки / теги | Усі issues / PR | Відкриті issues / PR |
| --- | --- | --- | --- | --- | --- |
| `ikstv/AvelRen` | public | `4a8e010aeb02d2d77fef3fc1297e67f4f5e5ab27` | 19 / 2 | 44 / 156 | 8 / 11 |
| `ikstv/AvelRen-ops` | private | `5be9da8b433813a664b4d4e21a0a92bae91c56a0` | 2 / 0 | 0 / 1 | 0 / 1 |
| `ikstv/AvelRen-ORIGINAL` | public | `8fdb9c245dd57aa62c050659fd90888ead836bec` | не є старим джерелом | — | — |

Теги `AvelRen`: `archive/hotfix-echerha-v5-contract` (`6667c24`) і
`apk/0.1.0-e5ea3b8` (`e5ea3b8`). Вони мають бути включені до Git-архіву.

Для кожної додаткової гілки виконано GitHub comparison з її старою `main`:
зафіксовані відстань і список змінених файлів. Це достатньо для рішення
«не копіювати навмання», але не є доказом побайтової або поведінкової
еквівалентності кожного історичного коміту.

## Гілки `AvelRen`

| Гілка | Стан щодо старої main | Висновок |
| --- | --- | --- |
| `chore/repo-tidy` | 2 ahead, 44 behind | Старі аудити й `.gitignore`; зберегти в історії, не переносити. |
| `chore/state-refresh` | 62 ahead | Лише generated `STATE.md`; архів, не джерело поточного стану. |
| `codex/admin-access` | 5 ahead, 1 behind | Admin/migration/release-notice пакет. Admin-потік перенесений пізніше; `release_notice` не має готового sender/Play gate, тому це окреме рішення, а не автоматичний перенос. |
| `codex/automated-maintenance-window` | 5 ahead, 6 behind | Плашка maintenance перенесена; автоматизацію reboot/deploy не застосовувати без нового дизайну й production GO. |
| `codex/device-retention-cleanup` | 2 ahead, 5 behind | Retention замінено новішими migration/worker у Original; архів. |
| `codex/fix-launcher-icon` | 6 ahead, 5 behind | Містить retention і старий launcher asset. Код retention не переносити повторно; asset потребує окремої перевірки джерела й рішення для релізу. |
| `codex/held-out-forecast` | 13 ahead, 5 behind | Старий forecast/retention експеримент. Поточний missing/zero контракт ведеться окремо; не змішувати з push-виправленням. |
| `codex/premium-instructions` | 7 ahead, 5 behind | Нова продуктова обіцянка, яку не було погоджено для Original; архів. |
| `dependabot/docker/app/python-cae66f2` | 1 ahead, 11 behind | Застаріле dependency оновлення; Original має пізніші pinned source-залежності. Перевіряти лише в окремому security backlog. |
| `dependabot/docker_compose/compose-images-df86d7246b` | 1 ahead | Старе image update; не переносити без нового exact-image review. |
| `dependabot/github_actions/actions-b7e4a448d5` | 1 ahead | Кандидат security backlog; Actions update не блокує функції користувача. |
| `docs/readme-professional` | 1 ahead, 99 behind | Застарілий README rewrite; архів. |
| `docs/signal-has-a-date` | 1 ahead, 48 behind | Правила датованих доказів уже застосовуються в Original; архів. |
| `feat/launcher-road-a` | 1 ahead, 41 behind | Лише launcher visual. До перенесення потрібні provenance і рішення про дизайн. |
| `feat/privacy-page` | 3 ahead, 43 behind | Старі Caddy/privacy файли; privacy документи й runtime Original ведуться окремо. |
| `feat/truthful-server-badge` | 1 ahead, 38 behind | Server badge має новіший counterpart; потрібне телефонне приймання, а не копіювання старої гілки. |
| `fix/backup-grants-and-rate-limits` | 1 ahead, 35 behind | Права backup перенесені пізнішими міграціями; реальна off-host автоматична публікація лишається окремим operational blocker. |
| `fix/prod-observability-cleanup` | 4 ahead, 5 behind | Заміщено watchdog/provenance в Original; архів. |

Єдина додаткова гілка `AvelRen-ops`,
`codex/production-image-provenance-audit` (1 ahead), містить лише
`docs/audits/PRODUCTION-IMAGE-PARITY-2026-09-28.md`. Це історичний доказ,
який треба зберегти в Git-архіві, але не старий deployment runbook.

## Відкриті issues і PR: що ще справді лишається

Вісім відкритих issues не означають вісім неперенесених серверних функцій.

| Джерело | Поточне рішення |
| --- | --- |
| #196 automated maintenance | Плашка й ручне коротке вікно існують. Повна автоматизація reboot/deploy — окремий майбутній етап. |
| #111 missing/zero forecast | Міграції й контракти перенесені; це окремий прогнозний ризик із датою перевірки 29.10, не причина змішувати зміни в push runtime. |
| #110 two PCs | Операційна нотатка застаріла; замінена CONTRIBUTING і SECRETS-RECOVERY. |
| #26 hardening | Батьківський реєстр робіт, а не один невнесений компонент. |
| #25 privacy/runbooks | Основні документи є; остаточне privacy/deletion/access-log приймання ведеться окремо. |
| #23 supply chain | SBOM, pins і CI gate перенесені; Dependabot/CodeQL/Gradle verification та регулярні audits — окремий security backlog. |
| #19 FCM ownership | Ownership і обмежене Android recovery перенесені; delete-installation/cleanup та остаточне phone acceptance ще окремі. |
| #15 DB roles | DSN collector/watchdog уже прийняті; retirement legacy roles і Timescale job owners не виконувати без окремого пакета. |

Одинадцять відкритих PR відповідають гілкам вище. Вони не будуть
автоматично merge або переноситися. Усі 44 issues та 156 PR мають бути
збережені як метадані й обговорення в архіві, включно із закритою історією.

## Умови перед видаленням

1. Прийняти на телефоні розгорнутий серверний кандидат: поріг і час в'їзду,
   звук, «ОК», повтор через п'ять хвилин і ручне скасування.
2. Створити перевірені Git bundles **усіх refs і тегів** обох старих
   репозиторіїв, зафіксувати SHA-256 та успішний `git bundle verify`.
3. Експортувати всі issues/PR, коментарі, labels і зв'язки; зберегти exports
   разом із hashes у захищеному місці. Для приватного `AvelRen-ops` архів не
   можна публікувати або змішувати з public release assets.
4. Зберегти окремо погоджені бінарні ресурси з provenance. П'ять Play PNG
   вже перенесені; launcher assets із старих гілок потребують окремого рішення.
5. Перевірити, що робочий сервер, scheduled monitor і release process більше
   не посилаються на старі репозиторії чи їхні образи.
6. Окремо показати власнику готовий архів і лише після його явного дозволу
   видаляти або змінювати видимість старих репозиторіїв.

Поки ці пункти не виконані, обидва старі репозиторії залишаються джерелом
історії та recovery, а не кандидатами на видалення.
