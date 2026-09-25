# Аудит production restore orchestrator

Цей аудит визначає межу для наступного кроку перенесення. Сам orchestrator
не переносився й не запускався.

## Походження

Файли присутні в `ikstv/AvelRen` на main commit
`4a8e010aeb02d2d77fef3fc1297e67f4f5e5ab27` і їхні SHA-256 збігаються з
read-only evidence production checkout від 2026-09-23:

| Файл | SHA-256 |
| --- | --- |
| `deploy/restore-production.sh` | `e942086554fcd97c10ac91850d43f6af88f2123b70305ff5429b525e0ce26f5a` |
| `deploy/restore-production-contract-test.sh` | `be720ba77a43644ef93aec9518146719fbba326b43e5420bab4546445640c749` |
| `deploy/restore-production-integration-test.sh` | `616c62ba0cf50e58d0dab0c16fdcc1665f2f5a2ac4997c28dfcf3a524ddf50a5` |

Це підтверджує походження кандидатів, але не їхню сумісність із консолідованим
репозиторієм або право виконання на production.

## Ізольована перевірка старого кандидата

24.09.2026 `deploy/restore-production-integration-test.sh` пройшов на чистому
export main commit `4a8e010aeb02d2d77fef3fc1297e67f4f5e5ab27` у локальному
Docker Desktop. Тест підняв випадковий Compose-проєкт із синтетичними
TimescaleDB-базами та тестовими credentials. Він перевірив restore повного
dump, restore з префіксом міграцій 001–009 із подальшим migrate/schema gate,
read-only API smoke, порядок restart, readiness/freshness failure та відмову
за активної DB-сесії. Контейнер, volume і мережа цього проєкту після тесту не
залишилися.

Успішний результат стосується лише старого orchestrator у старій структурі
checkout та його синтетичного тестового середовища. Він не перевіряє новий
`ops/restore-engine.lib.sh`, реальну копію з Drive, decrypt ключ або production
database. `FATAL` після рядка успішного завершення походить від навмисного
завершення тестового `pg_sleep` процесу в сценарії активної сесії.

## Несумісність із перенесеним restore-кодом

У старому orchestrator є кілька production-side ефектів до виклику engine:
він зупиняє ingress і відомих DB-клієнтів, перевіряє сесії та намагається
зберегти pre-restore snapshot. Якщо подальший крок падає, його fail-closed
обробник навмисно залишає служби зупиненими.

Перенесений `ops/restore-engine.lib.sh` приймає лише `restore_test` і відхиляє
`avelren`. Старий orchestrator викликає engine саме з ціллю `avelren`. Якщо
підмінити лише шлях `deploy/` на `ops/`, engine відхилить цю ціль уже після
зупинки сервісів; failure handler залишить їх зупиненими. Отже, це не готовий
до прямого копіювання комплект.

Також потрібно окремо звірити:

- старі шляхи `deploy/` із новими `ops/`;
- Compose-контекст, env-файл, project directory та локальний migration pin;
- виклик migration gate з профілем `migrate`;
- фактичний стан ролей і міграцій. Під час аудиту 2026-09-23 production був на
  міграціях 001–009, а adoption/pin перехід залишався незавершеним;
- contract та integration tests production orchestrator із поточними
  restore-guard контрактами й актуальною схемою.

## Рішення цього етапу

Production orchestrator, його production-specific tests і старі командні
інструкції не копіювати до `ops/` зараз. Публічний CLI залишається обмежений
`restore_test`. Наступним кодовим кроком має бути окремий дизайн production
capability, який спершу доводить усі preconditions до зупинки сервісів і
зберігає окрему fail-closed межу від CLI для disposable restore. Після цього
потрібні адаптовані contract та ізольовані integration tests.

Детальні фази та межі наведено в
[дизайні production restore](PRODUCTION-RESTORE-DESIGN.md), а точні
розбіжності старого кандидата з поточним engine — у
[контрольній матриці](PRODUCTION-RESTORE-GAP-MATRIX.md).

Цей документ не містить команди запуску й не дозволяє розгортання чи
відновлення production. Будь-які server-side дії потребують окремої великої
команди власника та явного дозволу на конкретну операцію.
