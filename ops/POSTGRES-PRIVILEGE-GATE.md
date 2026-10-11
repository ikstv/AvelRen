# Перевірка прав PostgreSQL для схеми 001–016

Це перша частина перенесення legacy [AvelRen#15](https://github.com/ikstv/AvelRen/issues/15).
`services/backend/src/avelren/privilege_gate.py` замінює introspection-частину
`deploy/postgres-privilege-gate.sh` і `app/tests/test_db_privileges.py` зі старого
`AvelRen@4a8e010aeb02d2d77fef3fc1297e67f4f5e5ab27`.
Adoption і відкат зі старого
[ops runbook](https://github.com/ikstv/AvelRen-ops/blob/5be9da8b433813a664b4d4e21a0a92bae91c56a0/deploy/postgres-adoption-runbook.md)
ще потребують перенесення.

## Контракт

Gate читає каталоги PostgreSQL і журнал міграцій у read-only транзакції:

- сім обмежених ролей, elevated capabilities і відсутність role memberships;
- перелік 21 public relation і 11 sequences, власник та ефективні права
  таблиць/колонок/sequences, включно з `GRANT OPTION`;
- права схеми/БД і відсутність PUBLIC ACL на application objects;
- чотири application functions: власник, `SECURITY DEFINER`, безпечний
  `search_path`, право виконання й заборона runtime delegation;
- global/schema-specific default ACL migrator для майбутніх об’єктів;
- точний журнал 16 міграцій і SHA-256 source-файлів.

Адміністративна `avelren_admin` за чинним bootstrap є superuser-роллю;
gate не визначає її retirement. Він не доводить, що працюючий collector
вже використовує обмежений DSN: runtime cutover має окреме приймання.
Timescale extension functions і внутрішні chunks не входять до frozen public
ACL; їхні ownership/restore контракти належать наступному adoption-етапу.

## Запуск

Потрібні залежності чинного backend lock, без pytest. З кореня checkout:

```sh
PYTHONPATH=services/backend/src python -m avelren.privilege_gate
```

Єдина змінна доступу — `AVELREN_PRIVILEGE_AUDIT_DSN`, передана середовищем
захищеного процесу. Не записувати значення в argv, історію команд або Git.
`DATABASE_URL` не є fallback. Паролі й тексти помилок libpq не виводяться.

Коди: `0` — контракти збігаються; `1` — drift; `2` — неправильний виклик
або перевірка недоступна. JSON містить лише `status` і категорії проблем.
Gate не виправляє drift, не запускає Compose/pytest/migrate й не викликає
application functions. Міграції беруться з цього checkout; після зміни схеми
потрібна окрема адаптація gate і тестів.

## Ізольоване приймання

```sh
bash scripts/test_database.sh
```

Тести запускають справжній CLI на disposable TimescaleDB. Навмисні зміни
прав/схеми виконує лише адміністративна тестова фікстура; gate повинен
відхилити їх і залишити стан незмінним. Production DSN/volumes, upstream
та реальні токени не використовуються. Ця зміна не розгортає CLI на сервері.

Наступне: ownership inventory/fingerprint, forward/inverse adoption,
cutover DSN та відкат із тестами; production-операція потребує окремого GO.
