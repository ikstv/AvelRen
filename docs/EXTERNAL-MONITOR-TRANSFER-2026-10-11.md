# Зовнішній моніторинг — перенос 11.10.2026

[PR #118](https://github.com/ikstv/AvelRen-ORIGINAL/pull/118) злитий у main
merge-комітом `1fdcbf28c209f961cbc501c7f5d531c89d6082e8`.
Head `f94243c498f5610b194d2850f2fb6a68bbf69160` має 4/4 успішні CI checks,
17 unit/CLI/workflow tests PASS та незалежний review без Critical/Important.
Live приймання й постійний розклад залишаються відкритими.

## Уточнення статусу — 14.10.2026

ORIGINAL тепер PUBLIC за рішенням власника; нижчий розрахунок вартості описує приватний стан 11.10, а не поточний рахунок. Workflow лишається ручним: зміна видимості сама не вмикає schedule й не закриває live приймання або доставку сповіщень. Бюджет і налаштування workflow не змінювалися цим оновленням документації.

## Джерело та зміни

Джерело — [AvelRen 4a8e010](https://github.com/ikstv/AvelRen/tree/4a8e010aeb02d2d77fef3fc1297e67f4f5e5ab27):

| Старий файл | SHA-256 джерела | Ціль |
| --- | --- | --- |
| `deploy/classify_alert_channel.py` | `55f857305c9648e42ad659afb38e2c05bbe1e2fb359c4949c9d99fa145260b66` | [класифікатор](../scripts/classify_alert_channel.py), без змін байтів |
| `.github/workflows/external-health-monitor.yml` | `f123c1588278e0c1cec15eafc80f6a3d6fd1a83c7c09d1062d064b637a1091a6` | [ручний workflow](../.github/workflows/external-health-monitor.yml) |
| `app/tests/test_alert_channel_monitor.py` | див. commit джерела | [тести](../scripts/tests/test_alert_channel_monitor.py), адаптовано шлях і додано два CLI сценарії |

Workflow перевіряє публічний `/api/health`: outage, alert_channel та
undelivered_alerts. Збережено окремі labels, відкриття issue при проблемі
та закриття після наступного успішного ручного прогону. Класифікатор:
empty викликає тривогу одразу, три unknown поспіль — blind, transient unknown
не викликає тривогу. Це перевірка стану, не доказ показу push на телефоні.

Шлях classifier адаптовано; checkout закріплено SHA, credentials не зберігаються.
Вхідні значення health обмежено дозволеними значеннями перед використанням
у workflow outputs; приймається лише один JSON object, age — число або null.
Fixtures перевіряють malformed/multiple JSON і безпечний workflow/CI контракт.
Concurrency запобігає паралельним
прогонам, які могли б створити дублікати issues. Автоматичні CI contracts
працюють без production запитів і без issues:write.

## Ручний запуск і вартість

Власник погодив перенос спочатку лише з workflow_dispatch. Розкладу немає.
У GitHub Actions вибрати «Зовнішній моніторинг (ручний запуск)», потім Run workflow
на main. Такий запуск звертається тільки до власного health API й може
створити/коментувати/закрити monitor issues у ORIGINAL; це не запит до єЧерги.
У межах source-приймання live workflow не запускали.

Старий AvelRen публічний, ORIGINAL приватний. Два jobs кожні десять хвилин
означають щонайменше 8640 оплачуваних хвилин за 30 днів після вичерпання
квоти; за Linux $0.006/хв це $51.84, без артефактів. Поточний бюджет $3
потребує окремого рішення щодо постійного розкладу. Довідка:
[GitHub pricing](https://docs.github.com/en/billing/reference/actions-runner-pricing).

## Межі приймання

Старий scheduled monitor залишається активним. Source-перенос і unit/CLI
тести не закривають live acceptance, автоматичний розклад або notification
delivery. Старий workflow/репозиторій не вимикати й не видаляти до
приймання заміни. Production deployment, DSN, БД й Android не змінюються.
