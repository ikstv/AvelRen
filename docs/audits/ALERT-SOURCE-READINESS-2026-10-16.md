# Готовність коду сповіщень — 16.10.2026

Звірено Git-історію, поточний код і GitHub Actions для `main`
[`0f4e1f6c50cbd49926d36bdd3bf35a3136c21258`](https://github.com/ikstv/AvelRen/commit/0f4e1f6c50cbd49926d36bdd3bf35a3136c21258).
Цей запис уточнює попередні статуси незавершеної реалізації, CI та злиття
в [залишках перенесення](../MIGRATION-REMAINING.md),
[реєстрі готовності](../RELEASE-READINESS.md) і
[аудиті ACK від 15.10](../ALERT-ACK-RESEND-2026-10-15.md).
Датовані попередні записи зберігаються як історія.

## Що вже є в main

| Зміна | Злиття | Перевірений результат у коді |
| --- | --- | --- |
| [PR #144](https://github.com/ikstv/AvelRen/pull/144) | `8fdb9c245dd57aa62c050659fd90888ead836bec` | Повтори threshold/ETA до ручного скасування; ACK не завершує моніторинг. |
| [PR #142](https://github.com/ikstv/AvelRen/pull/142) | `5b6346f9ef278fd8e08b631e2105300301b6bbb1` | Мінімальний legacy alert hotfix зі збереженням контракту повторів. Наявність пакета в Git не означає його встановлення. |
| [PR #146](https://github.com/ikstv/AvelRen/pull/146) | `f87a4de7d26b43a811c8041f91a9a05ff61c9514` | Android запускає звірку активних сповіщень одразу після успішного DELETE підписки або ETA-цілі. |
| [PR #147](https://github.com/ikstv/AvelRen/pull/147) | `0f4e1f6c50cbd49926d36bdd3bf35a3136c21258` | ACK оновлюється для кожної нової доставки; notifier записує `clock_timestamp()` після успішного send. |

Повторно реалізовувати ці зміни через старі записи «ще не злитий» або
«окремо реалізувати» не потрібно. Відоме обмеження ACK-протоколу лишається:
запит містить alert ID без номера доставки, тому запізнілий ACK попередньої
доставки неможливо відрізнити від ACK нової.

## Перевірка CI саме основної гілки

[CI run 38933056005](https://github.com/ikstv/AvelRen/actions/runs/38933056005)
має `event=push`, `head_sha=0f4e1f6c50cbd49926d36bdd3bf35a3136c21258`,
`run_attempt=1`, `status=completed`, `conclusion=success`.
Запуск почався 16.10 о 16:34:45 UTC і завершився о 17:19:52 UTC
(20:19:52 за Києвом).

| Jobs цього run | Результат |
| --- | --- |
| `scope`, `backend_core / core`, `api / api`, `database / database`, `watchdog / watchdog` | `success` |
| `android / android`, `repository / repository` | `success` |
| `supply_chain / source-sbom`, `supply_chain / image-sbom`, `CI gate` | `success` |
| `monitor_contracts` | `skipped`; це не окремий успішний тест monitor contracts. |

Усі 11 jobs належать тому самому SHA. Для цього run GitHub повернув три
артефакти з відповідним `head_sha` та `expired=false`:

| Артефакт | GitHub artifact ID |
| --- | --- |
| `ci-plan-0f4e1f6c50cbd49926d36bdd3bf35a3136c21258-38933056005-1` | `12060156147` |
| `source-sbom-0f4e1f6c50cbd49926d36bdd3bf35a3136c21258` | `12059178200` |
| `runtime-image-sbom-0f4e1f6c50cbd49926d36bdd3bf35a3136c21258` | `12059757402` |

Перевірено метадані артефактів; їхній вміст у цій звірці не аналізувався.
SBOM-артефакт не є серверним пакетом і не підтверджує deployed image.

Окремий [scheduled monitor run 38945231554](https://github.com/ikstv/AvelRen/actions/runs/38945231554)
на цьому самому SHA завершився `success`. Це результат одного запуску,
а не приймання доставки push, звуку чи failure/recovery на телефоні.

## Локальна перевірка та межа середовища

На чистому checkout цього SHA виконано:

- `python scripts/verify_ci_scopes.py`: 26 прикладів і контракти supply-chain
  workflow та aggregate gate пройшли.
- `python scripts/verify_core_provenance.py`: перевірено 21 core, 14 DB,
  17 API та 3 watchdog записи.
- `python scripts/verify_android.py`: перевірено 64 вихідні записи та
  походження ресурсів.

Штатний `bash ops/build-candidate-image.sh` запущено з чистої `main`.
Він зупинився на виклику `docker build`: `docker: command not found`,
exit code 127. Образ, його digest і результат перевірки встановленої моделі
не отримані. Локальних Docker/БД репетицій у цьому середовищі не було;
серверні та Android результати вище належать зазначеному hosted CI.

## Наступний завершуваний етап

1. У середовищі з Docker звірити актуальну чисту `main` і її CI та зібрати
   кандидат штатним `ops/build-candidate-image.sh`. Зберегти повний source
   SHA, image digest і результат перевірки моделі всередині образу.
   Якщо `main` змінилася, цей CI-запуск не приймає новий SHA автоматично.
2. За [deployment preflight](../DEPLOYMENT-PREFLIGHT.md) і
   [контрактом доказів](../DEPLOYMENT-EVIDENCE.md) підготувати точний список
   змінюваних служб, перевірити їхню runtime-сумісність та ізольовані тести,
   зафіксувати поточні образи й відкат. Source #147 змінює API і notifier;
   потребу оновлення collector/watchdog визначає окремий свіжий readback.
3. Показати власнику готовий пакет, перевірки та спосіб відкату й отримати
   окремий явний дозвіл на конкретну production операцію. Попереднє DSN
   приймання чи злиття PR не є таким дозволом.
4. Підготувати Android-кандидат із чистої актуальної `main` з commit,
   версією і SHA-256. Для встановленого Play-застосунку врахувати
   [зафіксовану різницю сертифікатів](../RELEASE-READINESS.md#підписаний-production-apk-кандидат--14102026):
   пряме оновлення локальним upload-signed APK не прийняте.
5. Для threshold і ETA окремо перевірити перший push і звук, «ОК», повтор
   через п'ять хвилин, повторний «ОК», foreground reconciliation та ручний
   DELETE. Доказ містить точний APK, дату й результат кожного сценарію.

Результат цього етапу — підтверджені source і main CI та визначений
наступний пакет робіт. Production, телефонне приймання, публікація 1.0.4,
retirement legacy ролі/Timescale jobs і завершення перенесення залишаються
окремими незакритими етапами. У цій звірці production не підключали,
секрети не отримували, контрольні push не надсилали.
