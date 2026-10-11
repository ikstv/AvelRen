# Інтеграція підготовлених переносів — 11.10.2026

Цей підсумок уточнює статус PR у [попередньому аудиті](MIGRATION-SERVER-2026-10-11.md).
Датовані спостереження сервера залишаються чинними лише на момент того аудиту.

## Прийнято в main

| PR | Перевірений head | Успішні CI checks | Merge-коміт |
| --- | --- | --- | --- |
| [#106](https://github.com/ikstv/AvelRen-ORIGINAL/pull/106) | `1c77c0cf604c448bfbea6b14c9e2ded80a334c36` | 7/7 | `4417739328d1a04b2f134b1feef566da001ee631` |
| [#107](https://github.com/ikstv/AvelRen-ORIGINAL/pull/107) | `b1910ef949709f7d84e13652450efc57c30b898e` | 5/5 | `297ae1d3bbdb66bb4f4fe56de4fee067282d61b5` |
| [#113](https://github.com/ikstv/AvelRen-ORIGINAL/pull/113) | `af5c2a6a10f6e692ff3dc017c74d22cfca26685e` | 7/7 | `cc12dc9d8d6eff343011afa204d9632847484dd1` |
| [#114](https://github.com/ikstv/AvelRen-ORIGINAL/pull/114) | `4091b2418b13eb728382a697d11812dec727d65e` | 6/6 | `b325bf9792e44a9afc386ba95dedc09d596c6029` |
| [#115](https://github.com/ikstv/AvelRen-ORIGINAL/pull/115) | `04c0985a5ef15ab5575e04ad9883c860a8b3f17b` | 6/6 | `0d524159bf9037c4e87de44ffd7e61188e921390` |
| [#116](https://github.com/ikstv/AvelRen-ORIGINAL/pull/116) | `6eb181318f70711a9664dea12dc1df70e1197acf` | 6/6 | `c9e8776ca9991cb64601aa102338a2dccd77db79` |

Злиття послідовні, без force-push; перед кожним перевірено точний head,
результати CI та фактичний MERGED. Залежні PR перед злиттям переведено на main.
Результати CI heads не замінюють окремий CI merge-комітів main.

Повторний CI main `c9e8776` та документаційного PR #117 не розпочав jobs:
GitHub повідомив про невдалу оплату акаунта або потребу збільшити spending
limit Actions. Це зовнішній блокер запуску, а не результат тестів.
Після відновлення Actions потрібно повторити ці прогони; main CI
цим підсумком не оголошено успішним.

## Спільні ізольовані перевірки

- 453 backend unit-тести на поєднаному коді; provenance чотирьох серверних manifests,
  Android provenance та контракт поділу CI.
- 43 adoption DB-тести, обмежений backup pg_dump та очищення disposable ресурсів.
- Повна синтетична restore-репетиція: schema/API smoke, збереження даних,
  adoption forward/inverse без зміни даних і журналу міграцій.

Помилковий перший DB-прогін із перемиканням checkout під час тесту відкинуто;
доказом є повторний успішний прогін на незмінній гілці.
Це синтетичні disposable перевірки, не відновлення актуального cloud backup
і не приймання production recovery PostgreSQL/SQLite spool.

## Наступні роботи

Підготувати production ownership/ACL executor і відкат, прийняти актуальну
резервну копію ізольовано, узгодити PostgreSQL/spool recovery та перенести
external health monitor зі старого AvelRen. Чинний старий monitor зберігати
до приймання заміни. Деталі — у [залишках перенесення](../MIGRATION-REMAINING.md).

Ці злиття не виконують production adoption, DSN cutover, deployment,
restart, міграції або робочий restore. APK, телефон і Play мають окреме
[приймання](../RELEASE-READINESS.md). Старі репозиторії зберігаються.
