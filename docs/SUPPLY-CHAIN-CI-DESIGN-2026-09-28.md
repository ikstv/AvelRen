# Дизайн supply-chain перевірок CI

**Стан на 28.09.2026.** Перевірено `AvelRen-ORIGINAL` main
`c3630eb3c93a6e4e297ec274d854325c35f8066e`, workflow, legacy PR #140,
issue #23, видимість/власника репозиторію та поточні правила GitHub.
Цей документ фіксує рішення для наступного кодування; CI і settings тут
не змінювались.

## SBOM: рекомендований обсяг

1. Додати окремий `supply-chain.yml`, щоб SBOM не запускав усі компонентні
   тести повторно. Запускати для PR і push у `main` за змінами manifests,
   lock-файлів, Dockerfile, Compose та самого workflow.
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

Наступна реалізаційна задача: додати лише source SBOM artifact за пунктами
1–4, перевірити його на PR і main, а container image SBOM винести в окремий
етап після узгодження candidate image pipeline. CodeQL пункт позначати
blocked-by-license, а не як неготовий workflow.
