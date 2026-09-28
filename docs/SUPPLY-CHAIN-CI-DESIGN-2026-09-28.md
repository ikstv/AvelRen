# Дизайн supply-chain перевірок CI

**Стан на 28.09.2026.** Перевірено `AvelRen-ORIGINAL` main
`4cc23bf106390f2236502019c27615fb05f3bf1a`, workflow, legacy PR #140,
issue #23, видимість/власника репозиторію та поточні правила GitHub.
Цей документ фіксує рішення для наступного кодування; CI і settings тут
не змінювались під час початкового аудиту.

## SBOM: рекомендований обсяг

1. Окремий `.github/workflows/supply-chain.yml` запускається незалежно від
   компонентних тестів на кожен PR у `main` і push у `main`: легкий
   source scan виконується швидко, а широке охоплення не пропускає нові типи
   manifests/lock-файлів через неповний path filter.
2. Генерувати CycloneDX JSON для дерева вихідного коду. Це описує залежності,
   які Syft розпізнає в репозиторії; це не є переліком пакетів усередині
   production container images.
3. Зберігати файл як обмежений за строком GitHub Actions artifact. Не додавати
   SBOM до public release assets: репозиторій приватний, а його залежності й
   структура є внутрішньою інформацією. Для release asset потрібна окрема
   явна зміна політики й обмежений job token.
4. Для мінімальних прав вимкнути в `anchore/sbom-action` його власне завантаження
   artifacts/release assets; записати файл у `$RUNNER_TEMP` і передати окремому
   `actions/upload-artifact`. Pin-ити обидва Actions повними SHA. На job
   встановити лише потрібний read scope, `persist-credentials: false`, без
   секретів і без dependency snapshot submission.
5. Окремим майбутнім критерієм додати SBOM runtime images: TimescaleDB і Caddy
   за їхніми точними digest, а `avelren-app` — після складання саме того
   candidate image, який перевіряє release/deployment pipeline. Не видавати
   source tree SBOM за image SBOM.

Syft action вміє сканувати директорії та images, генерувати SPDX/CycloneDX,
а його стандартне завантаження artifact використовує ширші permissions.
Див. [Anchore SBOM Action](https://github.com/anchore/sbom-action) і
[GitHub Actions artifacts](https://github.com/actions/upload-artifact).

## CodeQL: поточний блокер

`AvelRen-ORIGINAL` — приватний репозиторій власника типу `User` (`ikstv`),
не організаційний репозиторій. GitHub документує code scanning/CodeQL для
публічних репозиторіїв або для приватних репозиторіїв організацій із
GitHub Team/Enterprise та GitHub Code Security. GitHub CodeQL CLI умови
також забороняють automated analysis/CI над закритим кодом без комерційної
ліцензії. Тому не додавати legacy CodeQL workflow і не запускати CodeQL CLI
для цього приватного коду за поточних умов.

Джерела: [CodeQL для приватного репозиторію](https://docs.github.com/en/code-security/reference/code-scanning/troubleshoot-analysis-errors/private-repository-enablement),
[умови GitHub CodeQL CLI](https://github.com/github/codeql-cli-binaries/blob/main/LICENSE.md).
API не повернув `security_and_analysis` налаштувань для цього токена; це не
змінює висновок щодо user-owned private repo. Власника/видимість не змінювати.

Якщо CodeQL стане обов'язковим, спершу потрібне окреме рішення власника:
перенесення репозиторію до організації з потрібним планом/ліцензією або
залишення CodeQL поза scope та окремий вибір аналізатора, ліцензія якого
дозволяє CI над закритим кодом.

## Межі legacy #140 та issue #23

Legacy PR #140 лише оновлює pins SBOM/CodeQL Actions у workflow старого
репозиторію. Він не є готовою реалізацією для компонентної CI-структури
ORIGINAL і не підтверджує право запускати CodeQL на приватному коді.
Issue #23 ширша: Python hashes і container digests уже частково прийняті;
Gradle locking/checksum, Dependabot, audits і локальний test-stack cleanup
потребують окремого інвентарного рішення.

Поточна реалізація pin-ить Anchore SBOM Action `v0.24.2` і Syft `v1.51.1`,
а також GitHub `upload-artifact v7.0.1` повними SHA. Container image SBOM
винести в окремий етап після узгодження candidate image pipeline. CodeQL
пункт позначати blocked-by-license, а не як неготовий workflow.

Перевірка фактичного artifact на main виявила, що Syft не підхопив 35 Python
пакетів із `requirements.lock`, тоді як Android lock дав 357 Maven-компонентів.
Syft Python cataloger розпізнає `*requirements*.txt`; тому workflow тимчасово
створює поруч `requirements.txt` з точним вмістом hash-locked файла, валідує
наявність кожного pinned пакета в CycloneDX і завжди прибирає копію.
Див. [підтримувані Python manifests Syft](https://oss.anchore.com/docs/capabilities/python/).
