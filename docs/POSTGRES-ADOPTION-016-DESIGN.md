# Перехід власності та прав PostgreSQL 001–016: дизайн для перегляду

Дата: 08.10.2026. Статус: пропозиція, реалізація ще не розпочата.

## Мета та підстава

Перенести ownership/adoption і перевірений відкат зі старих AvelRen та
AvelRen-ops до AvelRen-ORIGINAL, адаптувавши їх до чинних міграцій 001–016.
Цей етап створює код і disposable-докази; він не виконує production-операцій.
Власник доручив продовжити перенесення після privilege gate PR #106.

Джерела:

- [legacy adoption та ownership library](https://github.com/ikstv/AvelRen/tree/4a8e010aeb02d2d77fef3fc1297e67f4f5e5ab27/deploy):
  `postgres-adopt.sh`, `postgres-ownership.lib.sh`, contract/topology/integration tests.
- [legacy runbook](https://github.com/ikstv/AvelRen-ops/blob/5be9da8b433813a664b4d4e21a0a92bae91c56a0/deploy/postgres-adoption-runbook.md).
- ORIGINAL main `db8b0db4ad5cbc4b15b815afb4c1d35000a1cda9` і
  [PR #106](https://github.com/ikstv/AvelRen-ORIGINAL/pull/106), head
  `f03fdaac15c9f1421a71d58070ffc9c8ebbd4a14`, усі сім CI checks успішні.
- Read-only аудит 08.10: production journal 001–016; legacy superuser ще
  використовується частиною runtime. Це датований факт, не передумова
  майбутньої операції.

## Вибір підходу

Рекомендовано Python-модуль поруч із privilege gate, psycopg для каталогу
та складання SQL із коректним quoting. Це дозволяє використати один
контракт прав 001–016 і не підтримувати паралельні ручні ACL-переліки.
Переносимо поведінкові гарантії legacy, а не копіюємо його старі припущення.

Альтернатива — адаптувати великий shell/awk сценарій: менше змін у формі,
але другий контракт прав і складніша обробка grantor/GRANT OPTION.
Повторне виконання bootstrap або міграції 010 не підходить: воно не
забезпечує точного відкату та не враховує нові функції/колонки/surge.

## Межі першої реалізації

Додати read-only inventory, fingerprint, forward/inverse планування та
виконавець для одноразової тестової БД. CLI відхиляє production apply:
потрібні явний test mode, ім'я БД зі штатним disposable-префіксом і
збіг із наданою ціллю. Немає fallback на application DATABASE_URL.
DSN передається тільки захищеним середовищем, не argv і не evidence.

Production orchestrator, зміни Compose/systemd, stop/start служб, DSN
cutover, provisioning/retirement ролей і ротація паролів не входять у цей
PR. Їхній runbook переноситься як послідовність майбутніх окремих операцій
із передумовами та відкатом, без придатної до випадкового запуску команди.

## Контракт inventory

Знімок збирається в read-only repeatable-read транзакції. Він включає:

- цільову БД, public та інші прикладні схеми, власників і ACL;
- 21 application relation, 11 sequences і чотири application functions;
- column ACL, function owner/definition/search_path/security mode;
- global і schema-specific default ACL, grantor, grantee, privilege та
  grant option; для NULL ACL враховуються PostgreSQL defaults;
- ролі без паролів, memberships, залежності, індекси, triggers, policies,
  extension membership і journal 001–016 із SHA-256;
- Timescale hypertables, chunks, compressed relations, continuous-aggregate
  bindings та пов'язані внутрішні об'єкти; shared ownership поза цільовою
  БД позначається окремо й не стає об'єктом зміни.

Порядок рядків і об'єктів канонічний, назви кваліфіковані схемою;
fingerprint SHA-256 не залежить від порядку запиту або фізичних OID.
Дані application tables та секрети не записуються в inventory.
Файли evidence приватні; запис атомарний, існуючі файли не перезаписуються,
symlink/reparse-point і пошкоджені чи невідомої версії inputs відхиляються.

Fingerprint для відкату порівнює семантичну власність і ефективні ACL
разом із grantor/GRANT OPTION, а не внутрішній спосіб зберігання NULL ACL.
Безпосередні UPDATE системних каталогів заборонені. Незмінність journal,
визначень об'єктів і synthetic data перевіряється окремо.

## Цільовий стан та незмінні об'єкти

Власник application relations/sequences/functions — avelren_migrator.
Ефективні database/schema/table/column/sequence/function/default права
точно відповідають контракту PR #106. Application function bodies,
SECURITY DEFINER і search_path не переписуються: невідповідність цьому
контракту є відмовою preflight, а не приводом для прихованого виправлення.

Власники БД, схем, extensions, системних каталогів і bootstrap-об'єктів
зберігаються зі знімка. Не використовується REASSIGN OWNED або DROP OWNED.
Timescale internal objects не стають ціллю довільного ALTER OWNER.
Побічні зміни Timescale ownership від штатного ALTER application root
мають бути виміряні на disposable TimescaleDB 2.30.1 і явно описані в
expected plan. Якщо вони не відповідають підтвердженій топології,
планування/приймання відхиляється. Інший extension/version/topology
потребує окремої адаптації.

Ролі повинні вже існувати й бути обмеженими; elevation/membership drift
відхиляється, а не виправляється. avelren і avelren_admin не змінюються.
Журнал усіх 16 міграцій, включно з applied_at, залишається незмінним.

## Forward, commit та inverse

1. Перевірити ціль, журнал, допустиму топологію, ролі та відсутність інших
   application sessions. Не завершувати чужі sessions автоматично.
2. Зберегти початковий знімок і SHA-256; згенерувати forward та inverse
   з того самого знімка, записати їх hashes і цільовий контракт.
3. Перед записом повторно перевірити fingerprint у транзакції після
   отримання application object locks. Встановити lock/statement timeout.
   Зміна між плануванням і виконанням — відмова до першої мутації.
4. Виконати лише явні ownership/ACL statements. Будь-яка помилка до
   commit відкочує всю транзакцію; новий знімок підтверджує початковий стан.
5. Після commit прочитати новий знімок, перевірити його та privilege gate
   через окреме read-only з'єднання. Зберегти committed receipt.
6. Якщо post-commit приймання не пройшло, inverse дозволений лише за
   цілісних evidence/plan hashes і відповідності фактичного стану
   зафіксованому committed snapshot. За новим drift — відмова, без
   перезаписування сторонніх змін. Компенсація не приховує початкову помилку.
7. Inverse повертає точні попередні власність і ACL у межах змінених
   об'єктів, включно з columns/functions/defaults та grant chains.
   При помилці inverse транзакція відкочується, результат —
   rollback_failed; жоден код не запускає runtime автоматично.

У разі збою між commit і публікацією receipt статус не називається
успішним або rolled_back. У evidence залишається intent із hashes;
окрема read-only діагностика визначає стан. Автоматичний повтор apply
за неповного evidence заборонений. Повторний apply до вже цільової БД
не змінює стан і повертає already_target із підтвердженим fingerprint.

## Приймання на одноразовій БД

- Поточна fresh 001–016: inventory стабільний, план має нуль змін.
- Legacy-like ownership/ACL поверх тих самих 001–016: forward проходить
  privilege gate, inverse повертає початковий семантичний fingerprint.
- Окремі topology cases: compressed hypertables, chunks та hourly continuous
  aggregate; synthetic restore зі штатними Timescale pre/post hooks.
- PUBLIC/column/function/default ACL, різні grantors, delegation chains
  і GRANT OPTION відновлюються точно або unsupported input відхиляється
  до запису. Не заявляти підтримку topology, яку не покриває тест.
- Відмова за journal drift, невідомих objects/ACL/role memberships,
  пошкодженого evidence, іншого target, активних sessions і drift після plan.
- Failpoints до commit, після commit і всередині inverse; перевірка
  rollback_failed і неоднозначного commit без фальшивого success.
- Production target, невідомі аргументи та writable DSN options для
  read-only inventory відхиляються. Помилки не розкривають DSN.
- Synthetic rows, journal/applied_at, passwords/roles та immutable
  objects зберігаються; upstream, production volumes і реальні токени
  у тестах не використовуються.

## Реалізація після перегляду дизайну

Окремий модуль inventory/planning, окремий disposable executor та тести
в services/backend; SQL quoting через psycopg.sql.Identifier/Literal.
Контракт privilege gate використовується спільно, без змін поведінки
самого gate. CI database запускає нові тести, provenance/docs зберігають
посилання на обидва джерела. Реєстр release readiness відділяє code/CI
від майбутнього production-приймання.

Гілка базується на PR #106, який ще не злитий. До інтеграції потрібні
послідовне приймання dependency та перевірки точного нового head.
Наступний документ після погодження — план реалізації з точними файлами,
інтерфейсами, TDD-перевірками та порядком commit.
