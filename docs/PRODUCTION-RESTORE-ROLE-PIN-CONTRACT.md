# Контракт evidence для ролей і migration pin у production restore

**Статус: source-only дизайн для review.** Це не runbook, не server-side
preflight і не дозвіл на production restore, зміну ролей або міграцію.

## Проблема, яку закриває контракт

Номер найновішої міграції сам по собі не говорить, який recovery-план сумісний
з фактичними ролями, grants і backup-артефактом. Особливо небезпечно виводити
role model з номера migration: production може бути на перехідному стані, а
restore має бути сумісним із конкретним, перевіреним recovery pin.

Тому майбутній internal-only orchestrator **не має default pin** і не може
автоматично обрати "найновішу" міграцію. Він має приймати тільки явно
схвалений pin, що належить зафіксованому source commit.

## Мінімальний sanitised evidence record

До першої maintenance-команди окремо схвалений read-only capture має містити:

```json
{
  "target_commit": "40 lowercase hex characters",
  "recovery_migration_pin": "NNN_migration_name from that commit",
  "database_journal": {"NNN_migration_name": "sha256"},
  "role_model": "explicit reviewed identifier, not inferred from pin",
  "roles": {
    "avelren_admin": {"login": true, "superuser": true},
    "avelren_migrator": {"login": true, "superuser": false},
    "avelren_backup": {"login": true, "superuser": false},
    "avelren_collector": {"login": true, "superuser": false},
    "avelren_notifier": {"login": true, "superuser": false},
    "avelren_watchdog": {"login": true, "superuser": false},
    "avelren_api": {"login": true, "superuser": false}
  },
  "role_memberships": {"role name": ["direct memberships only"]},
  "ownership_and_grants_verified": true
}
```

Реальний record не містить DSN, password, token, host name, IP, повного
`pg_roles` output або SQL-логу. Саме ці поля зберігають достатній доказ для
offline review без розкриття секретів та непотрібної topology-інформації.

## Fail-closed правила майбутнього gate

1. `target_commit`, migration file SHA-256 та `database_journal` звіряються з
   єдиним review source tree. Невідомий, відсутній або змінений migration file
   блокує операцію.
2. `recovery_migration_pin` має бути названий явно в плані й існувати у цьому
   source tree. Відсутній pin, "latest" або pin, виведений автоматично —
   відмова до будь-якої maintenance-дії.
3. `role_model` має бути окремо схвалений для цього pin і backup-артефакту.
   Gate не має прирівнювати `001–009` до least-privilege adoption і не має
   вважати наявність `010` доказом того, що рольовий перехід уже відбувся.
4. Усі очікувані ролі мають бути присутні. Для runtime-ролей evidence має
   довести відсутність superuser; для `avelren_admin` — точну очікувану
   адміністративну ідентичність. Будь-яка зайва або непридатна membership,
   owner чи grant блокує перехід до maintenance.
5. Перевірки виконуються read-only сесією. Паролі й DSN не передаються в argv,
   не зберігаються в evidence і не потрапляють у логи.

## Що ще потрібно перед реалізацією

Власник має окремо зафіксувати сумісну пару: recovery artifact lineage +
`recovery_migration_pin` + `role_model`. Лише після цього можна написати
parameterised source-only gate і його synthetic integration test. До такого
рішення цей документ навмисно не обирає pin і не створює production-команду.
