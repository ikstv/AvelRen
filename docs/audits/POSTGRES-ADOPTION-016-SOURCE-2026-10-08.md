# Source-приймання PostgreSQL adoption 001–016 — 08.10.2026

Кандидат `codex/postgres-adoption-016` побудований поверх PR #106,
`f03fdaac15c9f1421a71d58070ffc9c8ebbd4a14`. Це source/disposable acceptance;
production executor, deployment, provisioning, DSN cutover та retirement відсутні.
Міграції 001–016 і `ops/postgres-bootstrap.sh` незмінні.

## Перевірки

- Повний `bash scripts/test_database.sh`: 124 passed, 343.90s.
- Backend unit suite у pinned dependency image: 423 passed, 55.44s.
- `bash ops/postgres-adoption-restore-test.sh`: exit 0. Відновлена синтетична
  БД містить compressed observations і матеріалізований hourly aggregate.
  Forward/gate/inverse зберегли точний fingerprint, application rows,
  surge ACK/attempt та журнал 001–016 із applied_at.
- Ruff 0.16.8, source provenance, shell syntax і `git diff --check`: GREEN.
  На Windows Docker bind mount лише EXE002 виключено через неправильний
  executable-bit; Linux CI перевіряє штатний повний набір правил.

Незалежний whole-branch review `f03fdaa..1e195da` виконав reviewer
`gpt-6-astra`: 4 Important, 0 Critical/Minor. Усі чотири виправлено одним
проходом: 7 regression tests спочатку FAILED, потім 7 passed і повні suites GREEN.

1. Session advisory lock береться до repeatable-read snapshot, object locks —
   до першої snapshot-producing query. Concurrent grant під час очікування
   призводить до відмови зі збереженням grant.
2. Inverse перевіряє persisted apply-intent/committed records, version, target,
   plan digest та fingerprints. Missing/tampered proof не допускає inverse SQL.
3. Втрата відповіді на COMMIT повертає commit_unknown без повтору COMMIT,
   rollback або компенсації; connection закривається до виходу з context manager.
4. Inventory/fingerprint містять trigger enablement; disabled FK/application
   triggers та зміна стану після plan відхиляються.

GitHub CI перевіряється окремо для exact head draft PR; ці локальні докази
не є production acceptance. [Runbook](../../ops/POSTGRES-ADOPTION.md).

## Рішення під час реалізації та їх ціна

1. Повторно використано погоджений ізольований clone. Ціна помилки ізоляції —
   сторонні зміни в checkout; branch/status перевірені.
2. Chunk identities читаються через catalog relid; adoption subset додано до
   існуючого runner. Ціна несумісності каталогу — відмова inventory.
3. Evidence publication підтримує Linux; Windows відхиляється. Ціна — потрібен Linux.
4. Структура 001–016 зафіксована окремим семантичним контрактом. Нові міграції
   потребують явного оновлення цього контракту.
5. Фізичні OID у назвах лише catalog-confirmed internal RI triggers нормалізовані.
   Ціна надто широкої нормалізації — пропущений drift; user triggers лишаються точними.
6. Dynamic internal FK trigger count не заморожений; constraints та enablement
   перевіряються, всі instances лишаються у fingerprint. Ціна — потрібна уважна
   підтримка критеріїв internal trigger при зміні Timescale.
7. Compressed descendants змінюються через батьківські Timescale hooks.
   Неочікуваний побічний ефект зупиняє операцію на fingerprint mismatch.
8. Старий compressed-hypertable layout не підтримується. Ціна — окремі design/tests
   перед adoption такої production топології.
9. pg_database_owner схеми public збережений; actor — фактичний DB owner.
   Неочікуваний grantor/ACL призводить до transaction verification failure.
10. CI restore step замінений joined wrapper, який виконує попередні assertions.
    Ціна — збій доданого acceptance блокує database CI.
11. Українські заголовки задач не підтримані task-start parser; ledger ведеться
    вручну. Ціна — додатковий контроль bookkeeping.
12. Joined restore fixture містить історичний compressed row та hourly data;
    час перенесено INSERT/DELETE, бо partition-key UPDATE відхиляється.
    Ціна — timestamp optional fixture відрізняється від базової репетиції.
13. Production orchestration лишається поза PR. Ціна — live migration не завершена.
14. Після review повторно підтверджено Linux-only evidence. Ціна — Windows write
    недоступний до окремого доказу ACL приватності.
15. Delegated grant graph відхиляється. Ціна — потрібен окремий inverse executor
    для такої структури grants.
16. Після review підтверджено pinned2.30.1 та відмову інших layouts/версій.
    Ціна — несумісний production inventory буде відхилений.
17. Draft PR залежить від #106 і не merge. Ціна — неможлива незалежна інтеграція в main.
18. Використано вже погоджений draft-PR варіант без повторного меню skill.
    Ціна — це не дає дозволу на deployment чи merge.

Відкладених Minor findings немає.
