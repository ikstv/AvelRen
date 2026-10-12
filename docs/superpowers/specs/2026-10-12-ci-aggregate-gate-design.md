# Пропозиція єдиного CI-gate — 12.10.2026

Рекомендація: один `.github/workflows/ci.yml` без `paths` на рівні події; визначення потрібних компонентів, виклики reusable workflow та завершальний статус `CI gate`. Це дасть перевірюваний підсумок CI, але саме по собі не заборонить злиття в `main`.

## Межі та вихідний стан

Прочитано checkout `C:/AI/AvelRen/original-collector-pacing`, HEAD `c70dd8cf750f2d40d6a3d318817317ebb0e85a95` (база аудиту `eed0cb0` з переглянутим notifier). Цей документ не змінює репозиторій, workflows, Git, production, оплату або видимість. Тести не запускались. Свіжі API-факти надані основним аудитом: `main.protected=false`, enforcement вимкнений, rulesets повертає 403 із вимогою Pro для приватного особистого репозиторію. Тут ці API-виклики не повторювались.

| Чинний workflow | Вибір / зміст |
| --- | --- |
| `backend-core.yml` | Увесь backend, DB, provenance, telemetry; unit, lint, provenance; timeout 10 хв |
| `api.yml`, `watchdog.yml` | Backend, DB, усі `ops/**`, спільні fixtures/provenance; ізольовані DB/API/watchdog сценарії; по 15 хв |
| `database.yml` | Те саме плюс кореневі Compose/env/gitignore; restore/adoption, collector runtime/spool, Caddy, міграції, Timescale; 50 хв |
| `android.yml` | Android і вибрані API-контракти, provenance/assets/verifiers; JVM/lint/три тестові режими й заборона release; 20 хв |
| `repository.yml` | `.github/**`, docs, scripts та три кореневі Markdown; CI scopes і provenance; 5 хв |
| `external-monitor-checks.yml` | Класифікатор, `scripts/tests/**`, два monitor workflow; offline pytest; 5 хв |
| `supply-chain.yml` | Кожний PR до main і push main, без path-фільтра: source SBOM та candidate/runtime image SBOM; 10 + 25 хв |
| `external-health-monitor.yml` | Лише ручний live-monitor; `issues: write`; окремий від CI |

У п’яти компонентів є PR-фільтри шляхів і push лише main; PR-гілка призначення зараз не обмежена. `scripts/verify_ci_scopes.py` перевіряє 13 базових шляхів (26 перевірок для двох подій) для п’яти компонентів × дві події, три обов’язкові collector runtime команди та докладний supply-chain контракт. Він не доводить повноту всіх шляхів, запуск monitor/repository чи наявність фінального gate. Його `fnmatchcase` не варто оголошувати повною реалізацією glob GitHub.

## Варіанти

1. **Рекомендований: один dispatcher + reusable workflows.** Чіткий `needs`, результати одного запуску, жодного опитування API або додаткових write permissions. Старі job bodies залишаються у своїх файлах. Потребує одночасного перенесення тригерів і адаптації verifier.
2. **Один монолітний `ci.yml`.** Так само надійний граф, менше міжфайлових інтерфейсів. Великий diff і файл, особливо через database/Android/SBOM; складніший подальший перегляд. Вартість jobs практично така сама.
3. **Окремий aggregator над чинними workflow через API / `workflow_run`.** Менше початкового переміщення коду, але треба правильно зіставляти event, PR, SHA, run attempt і відсутні runs; очікування, races, timeout та привілеї збільшують складність. Відфільтрований workflow не створює завершення, якого можна дочекатися. Не рекомендується для цього бюджету й обсягу.

## Запропонований контракт

### Тригери, файли та інтерфейси

- `ci.yml`: `pull_request` без `paths` (зберегти всі поточні PR targets), `push.branches: [main]`; без schedule і feature-branch push. Події PR: opened, synchronize, reopened, ready_for_review, edited — остання потрібна для зміни target branch. Зберігати CI для draft PR. Назва фінального job рівно `CI gate`, унікальна в репозиторії.
- Вісім файлів `backend-core.yml`, `api.yml`, `database.yml`, `watchdog.yml`, `android.yml`, `repository.yml`, `external-monitor-checks.yml`, `supply-chain.yml`: `on: workflow_call`, без паралельних автономних PR/push тригерів. Виклики `uses: ./.github/workflows/<file>.yml`; жодних `secrets: inherit`, довільного ref або command input. Усі jobs checkout одного `github.sha`.
- `.github/ci-scopes.json`: version 1, фіксовані IDs та positive glob patterns, перенесені з наявних paths. Окремо задекларувати always-required `repository`; `supply-chain` обов’язковий для кожного PR до main і push main незалежно від шляхів, як зараз. Для інших PR targets supply-chain не required; чинні компонентні scopes зберігаються. Repository на кожній події — свідоме невелике розширення перевірки конфігурації.
- `scripts/ci_scopes.py`: чистий matcher + CLI, який читає event JSON, manifest та Git; друкує versioned JSON `complete`, `reason`, `event`, `base_sha`, `head_sha`, `tested_sha`, фіксовану карту восьми `required` boolean. Для `GITHUB_OUTPUT` — компактний JSON і фіксовані boolean outputs, ніколи сирі filenames. Підтримати лише потрібну граматику `*` / `**` / точні шляхи з документованими slash semantics; не додавати negation без окремого контракту.
- `scripts/verify_ci_gate.py`: чиста функція `evaluate(plan, needs)` та CLI, сувора схема, фіксований allowlist IDs; JSON надходить через env/файл. Жодного пошуку checks за іменем через API.
- `scripts/verify_ci_scopes.py`: читати новий manifest/call graph; зберегти всі чинні приклади та supply-chain assertions, замінити старі assertions `on.pull_request/push` для reusable SBOM перевіркою caller triggers і безумовного виклику. Додати відповідність manifest ↔ calls ↔ `needs`, відсутність подвійних тригерів, заборону job `continue-on-error`, перевірку потрібних internal jobs.
- `scripts/tests/test_ci_scopes.py`, `test_ci_gate.py`, `test_ci_workflow_contract.py`: нові локальні регресії. `test_external_monitor_workflow.py` має й далі доводити manual-only live-monitor та відсутність live-запитів/issue writes у CI.
- Після реалізації: коротка датована примітка у `docs/MIGRATION.md`, `docs/MIGRATION-REMAINING.md`, `docs/RELEASE-READINESS.md`; не переписувати історичні аудити.

`scope` → вісім окремих workflow calls → `gate`. `gate.needs` явно містить `scope` і всі вісім calls; `if: ${{ always() }}`, timeout 2 хв. Виклик компонента має умову `needs.scope.outputs.<id> == 'true'`. Gate успішний лише якщо scope успішний, план валідний, кожний required call має `success`, а кожний non-required — `skipped` або `success`. `failure`, `cancelled`, missing/unknown result чи відсутній output — відмова. Заборонити приховані skip всередині обов’язкових reusable jobs; для SBOM потрібні обидва jobs. `always()` дозволяє перевірити результат залежностей після їхньої помилки; не гарантує запуск після примусового скасування всього workflow. [Семантика needs/if](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#jobsjob_idneeds).

### Шляхи, commits та відмови

Для PR обчислювати повний `merge-base(base, head)..head`; додатково об’єднувати з diff від першого батька до checkout merge commit, щоб покрити фактичний integration delta. Для push — `before..github.sha`. Читати `git diff --name-only -z --no-renames`: rename стає old deletion + new addition; враховуються обидва шляхи, видалення, Unicode, пробіли й newline. Об’єкти одержувати за перевіреними SHA, без виконання рядків із назвами гілок/файлів. Scope checkout має достатню історію (`fetch-depth: 0` для першої версії).

Нульовий before для нової main, відсутній merge-base або неможливий повний diff: запустити всі компоненти, записати причину; якщо неможливо гарантувати checkout/tested SHA чи валідність manifest — scope failure. Нова feature branch без PR не запускає CI за чинною push-політикою; створення PR запускає його. Незнайомий шлях поза явним allowlist docs-only та відомими scopes також запускає всі компоненти. Зміна dispatcher, manifest, gate/classifier/verifier або будь-якого `.github/workflows/**` запускає всі набори, включно з monitor contracts. Це консервативне розширення сьогоднішніх self-workflow paths.

Лише `docs/RELEASE-READINESS.md`: repository + обидва SBOM jobs + gate; Android і серверні набори пропущені обґрунтовано. Provenance JSON та `docs/ASSETS.md` зберігають власні залежності й не вважаються звичайною документацією.

Не використовувати обрізаний список файлів payload/API. Регресії мають охопити >300 і >3000 файлів із важливим шляхом наприкінці. Примітка: прочитана 12.10.2026 документація вже називає ліміт server-side path diff 3000, тоді як старі описи вказували 300; запропонований Git diff не залежить від обох меж. [GitHub path diff](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#git-diff-comparisons).

PR перевіряє synthetic merge commit; summary/artifact явно показують head, base і tested SHA. SBOM назви та embedded `SOURCE_COMMIT` продовжують означати tested `github.sha`, не лише PR head. Push main перевіряє фактичний merge-коміт окремо: це інше дерево/подія, а не дубль PR-run. Якщо base main змінився, старий зелений PR run не підтверджує нову інтеграцію; потрібні оновлення PR/re-run актуальної merge revision, а після доступності protection — відповідна вимога актуальності. [PR commit semantics](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#pull_request).

Видалений reusable файл або невалідний YAML можуть зупинити workflow до gate: це відсутній результат, ніколи успіх. Merge conflict, очікування approval fork run, Actions outage, витрачений бюджет або `[skip ci]` так само можуть залишити gate відсутнім. Назва «завжди запускається» означає відсутність path skip для придатної події, а не гарантію доступності GitHub.

### Збереження та довіра

Перенести job bodies без скорочення: full-SHA pins actions, versions Python/Java/Gradle/Syft, digest images, hash Compose, timeouts, locked installs, усі tests та negative release checks. Зберегти SBOM cleanup `always()`, validation до upload, SHA names, `if-no-files-found: error`, retention 30 днів, відсутність docker push. Top-level permissions `contents: read`, checkout `persist-credentials: false`; не додавати OIDC, issues/checks write або secrets. Live-monitor з його `issues: write` лишається manual-only поза графом CI.

Root concurrency для PR — окрема група за номером PR, `cancel-in-progress: true`; для push main — окрема група, не скасовувати активний main run. Стару Android workflow-level concurrency прибрати під час міграції: скасування контролює caller, без взаємного скасування caller/callee. Зберегти fork Gradle cache-read-only.

Локальний reusable виклик бере workflow з commit caller; він не робить YAML довіреним автоматично. [Reusable workflow resolution](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows#calling-a-reusable-workflow). Код, manifest і gate з PR можуть бути змінені автором PR: цей дизайн ловить звичайні помилки, але не є незалежним захистом від зловмисного переписування власного CI. Зміни CI мають бути явно переглянуті власником; майбутні required reviews/CODEOWNERS можуть підтримати це лише за належного enforcement. Не виконувати PR-код через `pull_request_target` чи привілейований `workflow_run`; не видавати fork secrets або write token. Результати fork із затриманим approval не трактувати як pass.

## Перевірка та перехід

1. **Підготовка:** один ізольований CI PR; перенесення всіх старих paths у manifest та bodies у workflow_call одним набором змін. Новий entrypoint і вимкнення старих автономних тригерів — в одному commit, без фази подвійних важких запусків. Без paid/visibility змін.
2. **Локальна перевірка:** scope/gate unit fixtures, чинний verifier, offline monitor tests, workflow syntax/schema validation. Перевірити структурним diff, що команди, pins, permissions та artifacts не загублені. Це пропоновані перевірки, зараз їх не виконано.
3. **CI приймання:** реальний all-scopes run міграційного PR; контрольні недорогі сценарії успіху/навмисної відмови/cancel/skip/missing. Не повторювати всю DB/Android матрицю заради кожного синтетичного результату — pure evaluator fixtures покривають комбінації. Перевірити фактичне ім’я `CI gate` і обидва SBOM artifacts.
4. **Захист після окремого рішення власника:** лише на доступному тарифі/моделі доступу зробити `CI gate` обов’язковим для main, визначити PR/актуальність і bypass. Прочитати effective API-конфігурацію та на контрольному failing PR довести блокування для фактичного merge identity, зокрема власника `ikstv`; потім на виправленому PR довести можливість злиття. Не достатньо самого PUT 200 чи існування ruleset. Якщо admin bypass дозволяє злиття failing PR, це обмеження потрібно прямо зафіксувати, а не називати повним enforcement. Зараз статус: **gate може бути реалізований; enforcement заблокований тарифом**.

Незалежний review — окремий prerequisite, не прихований default: PR цієї сесії створює `ikstv`, і self-approval автора не може замінити review іншою особою. До вимоги обов’язкового approval власник має визначити доступного reviewer та бажану модель bypass/доступу. Не налаштовувати недосяжний review, не обходити його admin merge. Запрошення людей, GitHub App, зміни доступу, billing або видимості цим документом не дозволені. Source gate можна завершити без заяви про enforceable reviews.

| Матриця приймання | Очікування |
| --- | --- |
| Усі 13 чинних cases × PR/push | Наявні п’ять компонентних відповідностей збережені |
| API/schema, DB, ops, Android, provenance, ordinary docs | Власні залежності + always repository/SBOM |
| Monitor scripts/tests або workflows | Monitor contracts; workflow edits запускають усі |
| Rename code → docs, docs → code; delete; дивні filenames | Обидва scopes, жодного shell виконання filenames |
| 301/3001+ paths; багатокомітний PR; force-pushed PR | Повний поточний diff, не лише останній commit |
| Новий before=0, недоступна історія, unknown path | Усі jobs; невизначений tested SHA/план → failure |
| Required success/failure/cancelled/skipped/missing | Лише success проходить; non-required skip дозволений |
| Scope failure, зламаний output, видалений needs/callee, continue-on-error | Тест контракту або gate failure; absent gate не pass |
| Fork, merge conflict, бюджет вичерпаний, skip-ci | Жодних secrets/write; pending/missing не pass |
| Новий commit під час PR-run, push main після merge | Старий run скасований, новий потрібен; main перевірений окремо |

## Вартість і рішення власника

Бюджет Actions $3/місяць не є дозволом придбати GitHub Pro. Цей дизайн не змінює billing. Додатково з’являються два короткі jobs (scope і gate), repository стає безумовним; усі важкі набори лишаються вибірковими, SBOM — безумовним як для main-PR зараз. Конкретна сума без виміряної тривалості, кількості подій, залишку включених хвилин і storage невідома. Оцінювати за фактичними billed minutes та artifact storage після одного приймального циклу; timeout — верхня межа, не прогноз витрат. Оплата приватних runners і storage залежить від використання та включених квот. [Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions).

Якщо $3 вичерпано, CI має залишитися незавершеним, а злиття — відкладеним за робочою домовленістю; не фарбувати пропущені тести зеленим і не підвищувати бюджет. Подальше скорочення SBOM запусків — окрема обґрунтована зміна покриття, не частина механічного aggregator.

Власнику не потрібне нове платне рішення для підготовки CI PR у вже дозволеному аудитному обсязі. Для **технічної заборони злиття** потрібне окреме рішення щодо плану або іншої придатної моделі репозиторію; зараз приватний Free цього не забезпечує. Публікація репозиторію не пропонується як автоматичний обхід. [Доступність branch protection](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches). До такого рішення gate — прозорий сигнал і дисципліна перевірки точного commit, не enforced protection.
