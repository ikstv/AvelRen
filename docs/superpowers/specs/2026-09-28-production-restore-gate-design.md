# Production restore gate: дизайн

Дата: 2026-09-28  
Статус: погоджена специфікація для планування; не production runbook і не дозвіл на restore

## Мета

Додати до `AvelRen-ORIGINAL` окремий internal-only шлях відновлення production
PostgreSQL/TimescaleDB, який не можна запустити випадково і який переходить до
maintenance лише після повного fail-closed preflight. Реалізація повинна
повторно використати перевірені source-only gates, але не розширювати публічний
`ops/restore.sh`, що назавжди залишається обмеженим базою `restore_test`.

Успіх означає, що синтетичний Docker integration test доводить повний порядок
від artifact verification до post-restore health checks, а всі відмови до
maintenance не впливають на запущений stack. Цей дизайн не запускає команди на
сервері та не дозволяє production deployment або production restore.

## Погоджені рішення

1. Production restore має окремий internal-only entrypoint. `ops/restore.sh`
   не отримує production flag або production target.
2. Перед destructive діями обов'язковий свіжий pre-restore snapshot. Якщо
   snapshot не створений або не пройшов integrity verification, restore
   припиняється.
3. Немає автоматичного rollback БД. Після початку maintenance помилка лишає
   ingress закритим і видає точну інструкцію для ручного recovery.
4. Production restore запускається лише вручну адміністратором. Таймер,
   webhook або інший автоматичний запуск заборонені.
5. Окремий явний GO власника потрібен перед server-side preflight,
   deployment або production restore.
6. Звичайне maintenance-вікно без `restarts_at` може тривати до 6 годин.
   Planned reboot лишається обмеженим 15 хвилинами. Після успіху ordinary
   maintenance прибирається відразу; після помилки лишається активним до
   ручного recovery або завершення погодженого вікна.

## Не входить у цей блок

- зміна production БД, ролей, grants, міграцій або контейнерів;
- завантаження реального backup із Google Drive;
- зберігання паролів, DSN, ключів rclone або topology у Git;
- автоматичний вибір «останнього» коміту, backup або migration pin;
- автоматичне повернення ingress після невдалого restore;
- зміна retention backup або публічного Android/API контракту.

## Компоненти

### 1. Internal-only orchestrator

Новий `ops/restore-production.sh` координує кроки, але не реалізує повторно
перевірки artifact, Compose identity або Timescale restore. Він source-ить
маленькі бібліотеки, зупиняється на першій помилці та веде журнал лише
нечутливих етапів.

Entrypoint приймає шляхи до backup, SHA-256 sidecar та схваленого evidence
record. Шляхи можуть бути аргументами; DSN, password, token і ключі — ні.
Секрети читаються тільки із захищеного environment-файлу чинного stack.

Перед maintenance скрипт вимагає інтерактивний confirmation token:

```text
RESTORE avelren YYYY-MM-DD
```

Token читається з TTY, не передається в argv, environment або лог. Дата —
поточна UTC-дата хоста. Неінтерактивний production-запуск заборонений;
contract tests використовують окремий test-only input descriptor.

Для restore використовується ordinary maintenance publisher без
`restarts_at`/`boot_id`. API й Android приймають такі вікна тривалістю до
21 600 секунд. Вікно з `restarts_at`/`boot_id` надалі має максимум 900 секунд,
тому довге restore-вікно не може показати неправдивий стан «Перезапуск
сервера».

### 2. Recovery evidence gate

Новий source-only gate перевіряє sanitised JSON record за контрактом
`docs/PRODUCTION-RESTORE-ROLE-PIN-CONTRACT.md`. Record містить:

- точний 40-символьний `target_commit`;
- явний `recovery_migration_pin` без значення `latest`;
- журнал migration name → SHA-256;
- явно названий `role_model`;
- очікувані ролі, direct memberships та факт перевірки ownership/grants;
- SHA-256 backup-артефакту, який має збігатися із sidecar.

Gate звіряє record з одним review source tree. Кожна migration до pin мусить
існувати, мати той самий SHA-256 та утворювати точний безперервний журнал.
Відсутня, зайва або змінена migration, невідома роль чи membership блокує
операцію. Pin ніколи не виводиться з production стану автоматично.

Конкретна recovery-пара не зашивається в код. Для кожного майбутнього запуску
вона окремо схвалюється як `artifact lineage + target_commit + migration pin +
role model`; це операційний вхід, а не значення за замовчуванням.

### 3. Існуючі gates

Orchestrator повторно використовує:

- `avelren_verify_restore_artifact()` із `ops/restore-artifact.lib.sh`;
- `avelren_verify_production_compose_identity()` із
  `ops/restore-production-identity.lib.sh`;
- окремий production engine, побудований із тих самих Timescale invariants,
  що `ops/restore-engine.lib.sh`, але без розширення allowlist `restore_test`.

Production engine не приймає довільний target. Його єдина допустима ціль —
точна production DB `avelren`, підтверджена Compose identity та evidence gate.

### 4. Pre-restore snapshot

Після повного read-only preflight, але до зупинки ingress, orchestrator створює
новий root-only snapshot через перевірений backup-контракт. Snapshot має:

- створюватися роллю `avelren_backup`;
- мати mode `0600` у directory `0700`;
- пройти мінімальний розмір, `gzip -t` та SHA-256 verification;
- отримати canonical one-line sidecar;
- бути перевіреним після запису до погодженого encrypted `rclone crypt`
  remote так само, як штатний backup.

Невдача dump, upload, remote read-back або digest comparison завершує процес до
maintenance. Тимчасовий plaintext видаляється trap-ом чинного backup-контракту.

## Послідовність виконання

### Фаза A: безпечний preflight

1. Перевірити root/admin контекст, TTY та точний confirmation token.
2. Перевірити права доступу до input-файлів без виводу їх вмісту.
3. Перевірити backup і sidecar.
4. Перевірити canonical production Compose identity.
5. Перевірити target commit, migration journal/pin і role model.
6. Перевірити current DB identity, ролі, direct memberships, owners і grants
   read-only запитами; у лог потрапляє лише pass/fail по категоріях.
7. Переконатися, що немає невідомих активних сесій, окрім власної preflight
   сесії та дозволених runtime-клієнтів.
8. Створити й remote-verify pre-restore snapshot.

Будь-яка відмова у фазі A завершується без maintenance, stop, drop або restart.

### Фаза B: maintenance і restore

1. Опублікувати стан «Технічні роботи». `restarts_at` не задавати, якщо
   окремо не погоджено фактичний host reboot: restore сам по собі не є reboot.
2. Зупинити ingress.
3. Зупинити відомі DB clients: API, collector, notifier і watchdog.
4. Повторно перевірити активні DB sessions; невідома сесія блокує restore.
5. Виконати Timescale `timescaledb_pre_restore()`, відновити dump та завжди
   спробувати `timescaledb_post_restore()` без маскування первинної помилки.
6. Перевірити relation allowlist, owners, grants, schema journal і SHA-256
   кожної migration до погодженого pin.
7. Запустити migration лише в межах явно погодженого target commit/pin; не
   застосовувати довільно новіші файли з робочого дерева.

### Фаза C: повернення сервісу

1. Запустити DB clients без ingress.
2. Перевірити schema gate, API health через внутрішню мережу, telemetry mount,
   watchdog snapshot і новий успішний collector run.
3. Перевірити canonical Caddy configuration без публічного traffic.
4. Запустити ingress останнім і негайно виконати зовнішній health check.
5. Якщо зовнішній check не пройшов, знову закрити ingress і лишити
   maintenance активним; завершити maintenance лише після успішного check.

## Поведінка при помилках

- До фази B: завершитися non-zero без зміни runtime.
- Після зупинки ingress: не відкривати ingress автоматично й не запускати
  destructive rollback.
- Зберегти первинну причину помилки навіть якщо cleanup або
  `timescaledb_post_restore()` також помилилися.
- Надрукувати нечутливий recovery summary: останній успішний етап, що лишилось
  зупиненим, шлях до перевіреного pre-restore snapshot і назву runbook-секції.
- Ніколи не друкувати secret values, DSN, environment dump, FCM token, rclone
  key або повний `pg_roles` output.

## Перевірки

### Contract tests

Команди Docker, PostgreSQL, backup, maintenance та service control
підміняються deterministic fakes. Тести доводять:

- правильний порядок preflight → snapshot → maintenance → restore → health;
- відсутність side effects при кожній preflight-відмові;
- блокування неправильного SHA, filename, target commit, pin, role model,
  membership, Compose identity та невідомої DB session;
- обов'язкове блокування при будь-якій snapshot-відмові;
- ingress запускається після всіх внутрішніх health checks, а невдалий
  зовнішній check негайно закриває його знову;
- після помилки у фазі B ingress лишається зупиненим;
- secrets не з'являються у stdout/stderr або argv fake-команд.

### Docker integration test

Окремий випадково названий Compose project створює синтетичну TimescaleDB,
backup і sidecar. Тест проходить повний restore через спільну нижньорівневу
Timescale primitive з test-only target. Production entrypoint окремим
контрактом доводить, що він hardcode-ить лише `avelren`; integration test ніколи
не використовує production volume, container name, `.env` або мережу. Він перевіряє:

- Timescale pre/post hooks;
- migration journal і SHA-256;
- relation inventory, owners і grants;
- schema/API smoke;
- active-session refusal;
- snapshot failure та помилку post-restore;
- cleanup лише ресурсів із випадковим test project label.

### CI gate

Shell syntax, contract tests, allowlist test та Docker integration test входять
до database workflow. Production entrypoint не може бути прийнятий, якщо будь-
який із них пропущений або не пройшов.

## Етапи після реалізації

1. Code review і зелений CI на точному commit.
2. Окремий source-only release candidate без server deployment.
3. Окремий явний GO для read-only production evidence capture.
4. Review sanitised evidence і вибір recovery-пари.
5. Окремий явний GO для deployment сценарію.
6. Ізольована restore rehearsal з реальним розшифрованим backup, але тільки у
   `restore_test`/staging.
7. Production restore виконується лише під час реальної recovery-потреби після
   окремого явного GO; сама наявність сценарію не є підставою запускати його.

## Критерії приймання дизайну

- `restore_test` і production entrypoint фізично розділені;
- snapshot failure завжди блокує restore;
- ordinary maintenance допускає не більше 6 годин, reboot — не більше 15 хв;
- до maintenance немає side effects;
- після maintenance немає автоматичного відкриття ingress при помилці;
- жодного default/latest pin і жодних секретів у Git, argv або логах;
- destructive production path неможливо активувати в Docker integration test;
- кожен production-side етап лишається за окремим authorization gate.
