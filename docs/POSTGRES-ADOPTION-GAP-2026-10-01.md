# Перехід прав PostgreSQL: звірка залишку

Зріз 01.10.2026, без доступу до production і без запуску сценаріїв зміни
прав. Порівняно `ikstv/AvelRen` на
[`4a8e010`](https://github.com/ikstv/AvelRen/tree/4a8e010aeb02d2d77fef3fc1297e67f4f5e5ab27),
`ikstv/AvelRen-ops` на
[`5be9da8`](https://github.com/ikstv/AvelRen-ops/tree/5be9da8b433813a664b4d4e21a0a92bae91c56a0)
і `AvelRen-ORIGINAL` на `a0cb2d2`. Побайтову інвентаризацію старих файлів
уже містять [SERVER-FILES.csv](SERVER-FILES.csv) та
[SERVER-IMPORT-INVENTORY.csv](SERVER-IMPORT-INVENTORY.csv); тут — функціональна
звірка, а не повторний перелік файлів.
Вихідна задача — legacy [AvelRen#15](https://github.com/ikstv/AvelRen/issues/15),
не однойменний номер issue у новому репозиторії.

| Контракт старого дерева | Стан у ORIGINAL | Висновок |
| --- | --- | --- |
| `deploy/postgres-adopt.sh` і `postgres-ownership.lib.sh`: знімок об'єктів та прав, fingerprint, forward/inverse plans, перевірка й аварійний відкат | `ops/postgres-bootstrap.sh` має `fresh` і disposable-only `roles-acl`; production adoption із доказами та inverse rollback немає | Не вважати bootstrap заміною сценарію переходу живої БД |
| `deploy/postgres-privilege-gate.sh` та `app/tests/test_db_privileges.py`: read-only перевірка контрактів окремих ролей без запуску міграцій | Еквівалентного gate для переходу production-ролей не знайдено | Адаптувати контракт і тести до поточної схеми; не запускати старий gate як production-приймання |
| Контрактні, topology й інтеграційні тести adoption у `deploy/` | Прямого набору adoption-тестів немає | Відтворити перевірки на одноразовій TimescaleDB та перевірити forward/inverse шлях |
| `AvelRen-ops/deploy/postgres-adoption-runbook.md`: етапи 3B.1–3F з окремими GO | Новий runtime, restore та документація існують, але завершеного плану cutover/retirement ролей немає | Старий runbook — історичне джерело, не актуальна команда для production |

## Чому пряме перенесення небезпечне

- У старій `postgres-ownership.lib.sh` функції `_canonical_relations` і
  `_canonical_target_acl_rows` перелічують об'єкти та ACL вручну. У них немає
  `admin_access` із міграції 011; нові міграції 012–014 також змінюють
  доступ до функцій і колонок. Потрібна повторна звірка всіх об'єктів,
  привілеїв, Timescale chunks і фактичної схеми, а не механічне копіювання.
- Історичний runbook для етапу 3B.2 очікує журнал до 009 і навмисно не
  позначає 010 застосованою до DSN cutover. За останнім записом
  [production-аудиту](PRODUCTION-AUDIT.md) у журналі вже 001–014 після окремо
  дозволеної 014. Це датоване свідчення, **не** свіжий стан сервера; перед
  будь-яким планом потрібна нова read-only перевірка журналу, схеми й ролей.
- У старому runbook після adoption ще окремі cutover, stamp, перевірка та
  retirement. Готовність лише етапу зміни ACL не означає готовності всього
  production-переходу. Новий `ops/postgres-bootstrap.sh` сам забороняє
  `roles-acl` поза disposable test DB.

## Наступний обмежений крок і умови приймання

Окремий design review має визначити бажаний кінцевий стан власності та ACL
для схеми 001–014, порядок cutover DSN, правила збереження/відкликання
legacy-superuser і відкату кожного етапу. Після рішення — окремий PR зі
сценарієм, який не приймає production за замовчуванням, та тестами на
одноразовому TimescaleDB: свіжий restore, inventory/fingerprint усіх
об'єктів, forward/inverse round-trip, grants для backup та кожної runtime-ролі,
відмова при drift, заборона автозастосування `migrate` під час gate. Порівняти
результат із поточною runtime Compose-моделлю, не зі старими overrides.

Ця звірка **не** підтверджує готовність до розгортання. Ні production, ні старі
репозиторії не змінювалися. Окремий явний GO і свіжі передумови потрібні
перед будь-якою операцією на живій БД.
