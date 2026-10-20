# Контрольований вихід collector з recovery_required

Це runbook локально підготовленого source-кандидата, не дозвіл на виконання на сервері. Стан конкретного deployment, CI й isolated acceptance вести окремо в [реєстрі готовності](../docs/RELEASE-READINESS.md).

## Що робить механізм

`collector-recovery-handoff.py` використовує ті самі backup/control locks і state_dir, що чинні служби. Journal зберігає старий state, manifest, file hashes, identity та intent кожного переходу. Звичайні backup/recover і mutating control відмовляють, поки journal не terminal. `resumed` означає підтверджене відновлення collector, а не публікацію копії.

| Команда | Результат |
| --- | --- |
| dry-run | Звіряє pins, owner/children, inventory, candidate та runtime contract; не змінює collector/state, може створити lock-файли |
| prepare | Стоп старого writer, safety SQL + Online SQLite + rollback spec, offline migration, journal prepared |
| switch | Один зупинений candidate з pinned identity, повні 60 monotonic секунд, старт candidate |
| finish | Native off ACK, drain без last_error, state resumed і journal complete |
| rollback | Зупинка доведеного writer, дві перевірки pending=started=0, reverse handoff, 60 секунд, старий writer; state recovery_required / journal rolled_back |

## Перед окремим server GO

1. Злити reviewed diff і дочекатися exact-head CI. Побудувати повний canonical backend з чистої main; перевірити installed bytes, UID, source SHA та export/load runtime image ID. Образ b009a27 попереднього кроку ще не містить нового migration модуля.
2. Підготувати цілісний host-пакет: новий handoff CLI, `paired_backup_state.py`, `paired-backup.py`; звірити залежні control/preflight/compose та installed paths. Новий helper/collector мають містити повний новий backend; зафіксувати helper source/image/module SHA. Оновлення host/helper pins є окремими server writes і входять у конкретний майбутній GO.
3. Оновити read-only UTC/boot/units+overrides, active container identities, state/manifest hashes, spool counts і дозволені mode fields. Старі факти 16.10 не гарантують поточного стану. Записати baseline API/notifier/DB/container restarts, незмінний Device ID fingerprint і 60s interval.
4. Погодити вікно. Зупинити timer лише після GO, довести відсутність іншого backup/restore/coordinator. Не скидувати locks/state, не починати другий collector, не запускати загальний Compose up або DB migrations.
5. Зберегти старий image/spec/env (секрети лише в захищеному місці). Новий приватний manifest має відрізнятися тільки image_id/source_commit. State_dir, env/compose paths, project/name/network/volume зберегти. Перевірити SHA tar до load і фактичний image ID після load.

### Склад host-пакета

Пакет містить сім source-файлів нижче з одного reviewed commit і SHA-256
кожного файла. Шляхи з аудиту 19.10 перед встановленням звірити повторно.

| Source в `ops/` | Призначення |
| --- | --- |
| `collector-recovery-handoff.py` | `/usr/local/sbin/collector-recovery-handoff.py` |
| `paired-backup.py` | `/usr/local/sbin/avelren-paired-backup` **і** `/usr/local/sbin/paired-backup.py`, однакові байти |
| `paired_backup_state.py` | `/usr/local/sbin/paired_backup_state.py` і sibling модуля runtime control |
| `paired_backup_manifest.py` | `/usr/local/sbin/paired_backup_manifest.py` |
| `collector-runtime-control.py` | `/usr/local/sbin/collector-runtime-control.py` і `<runtime-root>/ops/collector-runtime-control.py` |
| `collector-runtime-preflight.py` | Звірити `/usr/local/sbin/` та `<runtime-root>/ops/`; замінювати лише за відмінності |
| `compose.collector-runtime.yml` | Звірити `/usr/local/sbin/` і pinned runtime compose path; замінювати лише за відмінності |

Handoff імпортує sibling з буквальним ім'ям `paired-backup.py`, тоді як
systemd викликає `avelren-paired-backup`: одного перейменованого файла
недостатньо. Runtime shell wrapper викликає власний sibling control;
ізольований новий CLI bundle не усуває обхід interlock старим control.
Приватний rollback archive має зберегти всі попередні файли, їхні права
та факт відсутності нового файла, а також старі manifest/helper pins.
До terminal journal не можна повертати старі tools, які не знають interlock.

Dry-run не перевіряє всі SQL/helper/password/disk prerequisites. Їх перевірити
окремим preflight до prepare. Секретний backup environment лишається на
хості; для нового helper потрібні узгоджені source/image/module SHA pins,
а не копіювання старих pins. Новий image має містити migration модуль.

## Інтерфейс кроків

Виконувати один крок за раз з однаковими pins. Значення нижче отримують зі свіжого read-only preflight; вони не є готовими production pins. Python host-шляхи мають відповідати перевіреному пакету.

```bash
python3 /usr/local/sbin/collector-recovery-handoff.py dry-run \
  --manifest /etc/avelren/collector-runtime.json \
  --new-manifest /private/reviewed/collector-runtime.next.json \
  --stack /path/to/verified/production-stack \
  --generation "$GENERATION" \
  --state-sha256 "$STATE_SHA256" \
  --manifest-sha256 "$OLD_MANIFEST_SHA256" \
  --new-manifest-sha256 "$NEW_MANIFEST_SHA256"
```

Після прийнятого dry-run той самий argv застосовується до `prepare`, `switch`, `finish` (або дозволеного `rollback`). Службове backup environment передається чинним перевіреним механізмом EnvironmentFile, без друку значень або shell-eval env-файла. CLI повертає лише phase/generation або redacted denial; dry-run виводить безсекретний план. Не запускати standalone migration модуль на live spool: supported шлях — лише handoff після підтвердженого stop і safety capture.

На кожному кроці перевіряти фактичний journal/state, exact container identity і допустимі mode fields. Safety captures приватні й перевіряються за hashes та читаністю повторно перед мутаціями. SQLite status відкриває БД `mode=ro`, але mount допускає створення WAL/shm coordination files: readonly mount для WAL може відмовити навіть SELECT. Таблиці status helper не змінює.

## Міграція і завершення

Offline migration SQL — read-only repeatable read. Payload/cycle state й SQL primary rows зберігаються; атомарні per-cycle markers прив’язані до exact audited legacy writer і даних. Подальші replay/restore незалежно звіряють SQL. Modern rows без marker не отримують legacy послаблення. Aged ACK прибирає лише штатний prune; ручне видалення для проходження тестів заборонене.

Після finish потрібні п’ять природних циклів одного producer, pending=0, capture_only=false/mode_ack=false, свіжа ETA/SQL/API, незмінні інші services. Потім окремо погоджена нова paired copy: власний backup ID, publication/readback, stamp/receipt/state з тим самим ID; окремий off-host restore/replay та exact counts. Тільки після цих PASS повернути timer і перевірити next UTC. Старі receipt та systemctl reset-failed не доводять успіх нової спроби.

## Переривання та відкат

Повтор з тими самими pins дозволений лише для доведених durable before/after states. Після SIGKILL у start_intent exact candidate зупиняється і відраховуються нові повні 60 секунд. Інший boot, PID reuse або foreign job — відмова. Crash між recreate і фіксацією нового container ID також навмисно залишає перехід заблокованим: автоматичного adopt невідомого ID немає. Потрібен окремий перевірений план звірки; JSON/locks не редагувати.

Rollback до legacy дозволений тільки без pending/started і без живого modern writer. Якщо backlog з’явився, механізм зупиняється, зберігає spool/state/safety captures та interlock; legacy не стартує. Не відновлювати SQL або старий spool поверх нових даних. `rolled_back` не закриває backup recovery; для нової спроби потрібні свіжі state/manifest pins, попередній journal зберігається в audit history. Після `complete` для пізнішого відкату потрібен новий окремий план; поточний rollback CLI не є універсальним downgrade.

## Локальне приймання

- `sudo python3 ops/collector-recovery-handoff-contract-test.py` — Linux locks/fsync/proc, drift, crash/refusal, safety artifacts, image env binding, WAL SELECT.
- `python3 ops/collector-recovery-handoff-daemon-contract-test.py` — wiring та boundary checks.
- `bash scripts/test_database.sh` — міграція retained legacy ACK/pending/started, strict restore, SQL idempotence й наявні backend/DB регресії.
- `bash ops/paired-backup-integration-test.sh` — historical source fixture → real handoff/rollback/SIGKILL → modern native daemon → paired crypt publication/readback → disposable restore. HTTP тільки synthetic, мережа internal; образ legacy fixture відрізняється від production і явно так позначений.

Production, реальні remote credentials, timer і серверні volumes цими локальними тестами не перевіряються й не змінюються.
