# Оновлення безпеки urllib3 — кандидат 12.10.2026

У `services/backend/requirements.lock` замінено лише `urllib3==2.7.0`
на `urllib3==2.8.0` та два SHA-256 офіційних дистрибутивів. Решта 34 pins,
хеші й коментарі збережені без змін. Вихідна база — `c70dd8cf750f2d40d6a3d318817317ebb0e85a95`,
гілка — `codex/security-urllib3-20261012`. Оригінальне походження lock із
`ikstv/AvelRen` / `4a8e010aeb02d2d77fef3fc1297e67f4f5e5ab27` та його SHA-256
`95c3b247639b3e4e4113963c59a45291757c1a6486ff532e62e0c44ee6409989`
збережено в [CORE-PROVENANCE.json](CORE-PROVENANCE.json). Окрема revision
фіксує новий SHA-256 `309e49554d06540f6bfe26b1786f8e87b081dbab920595f6870e35d46807797f`.

## Підстава та межі

Read-only перевірка metadata точних 35 Python lock pins 12.10.2026
виявила один affected package: urllib3 2.7.0 і три різні CVE.
Парні GHSA/PYSEC записи не рахуються як додаткові вразливості.
Офіційні advisories зазначають patched version 2.8.0:

| Advisory / CVE | Affected versions |
| --- | --- |
| [GHSA-8988-9cw3-xx77 / CVE-2026-97687](https://github.com/urllib3/urllib3/security/advisories/GHSA-8988-9cw3-xx77) | `>=1.26.0, <2.8.0` |
| [GHSA-gh4c-6fx4-qh6g / CVE-2026-97688](https://github.com/urllib3/urllib3/security/advisories/GHSA-gh4c-6fx4-qh6g) | `>=2.6.2, <2.8.0` |
| [GHSA-vxq7-64xx-v4gw / CVE-2026-97689](https://github.com/urllib3/urllib3/security/advisories/GHSA-vxq7-64xx-v4gw) | `>=1.10.3, <2.8.0` |

[Офіційна PyPI metadata 2.8.0](https://pypi.org/pypi/urllib3/2.8.0/json)
вимагає Python `>=3.10` і містить два дистрибутиви:

| Дистрибутив | SHA-256 |
| --- | --- |
| `urllib3-2.8.0-py3-none-any.whl` | `0cf3cae568d36aa9576b28dfb35f11328f1cb974ca7647d9475ebb86c75ac6e3` |
| `urllib3-2.8.0.tar.gz` | `63bf2ead4c879426ebf22ef2a781eeb4aa3b4ae798a0435506f8687fd5bb9b63` |

Повторна перевірка всіх 35 точних pins за PyPI metadata після зміни:
0 affected packages, 0 помилок запиту. Це датований результат лише для
Python lock metadata. Контейнери, системні пакети, Gradle та live images
не входили до цього scan; загального CVE all-clear чи факту експлуатації
вразливостей цей запис не встановлює.

## Локальна перевірка

Wheel і sdist завантажено з офіційних PyPI distribution URLs, обидва
SHA-256 збігаються з metadata. Wheel встановлено через `--require-hashes`
в окремий похідний test image Linux / Python 3.14.7; `pip check` не виявив
пошкоджених залежностей. Повний lock звірено з установленими pins без
мережі. Requests 2.34.2 та google-auth 2.57.1 імпортуються, створення
HTTP adapter, Request та AuthorizedSession успішне без HTTP send.

Перед full unit у самому test runtime явно перевірено
`importlib.metadata.version('urllib3') == '2.8.0'`. Старий кешований test
image містив 2.7.0 й не є доказом перевірки нового pin. Unit виконано
з read-only source bind, `--network none` та `/tmp` tmpfs 4 GiB.
Результат: **669 passed, 2 warnings** за 36,87 с. Попередження належать
Starlette/httpx та AnyIO deprecations. Provenance всіх чотирьох manifests,
CI scopes (26 examples та supply-chain workflow contract), candidate image
attestation contracts, Ruff і `git diff --check` успішні. Hosted CI та
свіжий повний candidate SBOM мають підтвердити інтегрований commit.

## Готовність

Код — локальний source кандидат; незалежний review, інтеграція та hosted
CI ще очікуються. Server deployment потребує окремого дозволу й exact-image
перевірки. На production новий pin не встановлювали. Android-збірка,
телефонна доставка й Play цим dependency update не прийняті.
