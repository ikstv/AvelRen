# Репетиція відновлення на ізольованому стенді (Gate 11, крок B2)

> **Цей документ не є авторизацією.** Він описує процедуру, яку виконують на
> **одноразовому стенді**, а потім — на бойовому хості. Жодна команда нижче не
> торкається бази `avelren`, не зупиняє жодного бойового сервісу і не змінює
> нічого в `/opt/avelren`. Якщо якийсь крок здається таким, що торкається —
> зупинись і перечитай: значить, я помилився в тексті, а не ти в розумінні.

Процедуру прогнано на одноразових стендах тричі (розділ 12c), останній раз —
на артефакті бойового класу. Виправлення після кожного прогону в тексті вже є.
Порядок лишається: **стенд перед хостом**.

---

## 0. Що це доводить і чого не доводить

Репетиція відповідає рівно на одне питання: **чи можна з нашого нічного
зашифрованого артефакта підняти працездатну копію бази — не «файл
розпакувався», а «застосунок на ній працює»**.

Доводить:

| | |
|---|---|
| артефакт із ремоуту завантажується цілим і проходить `gzip -t` | крок 2 |
| дамп фізично завантажується в TimescaleDB з коректними pre/post-restore | крок 7 |
| набір прикладних відношень у дампі **точно** збігається з allowlist рушія | крок 7 |
| історія міграцій і фізичний контракт схеми цілі | крок 9 |
| справжній застосунок читає й пише відновлену базу (health, auth, devices) | крок 9 |

**Не** доводить:

- що ключ від crypt-ремоуту існує **поза** цим сервером (це `docs/backup-key-escrow.md`, окрема процедура);
- що бойове відновлення вкладеться у якийсь час (RTO/RPO не затверджені — `docs/disaster-recovery.md`);
- що `deploy/restore-production.sh` спрацює на бойовій базі (він іде іншим шляхом: зупиняє ingress, робить pre-restore snapshot, працює по продовому compose). Репетиція перевіряє **рушій і артефакт**, а не оркестратор.

### Виправлення попереднього твердження

Я раніше сказав, що «в проєкті взагалі немає операторської процедури
відновлення». **Це було неточно.** Є:

- `deploy/restore-production.sh` — повний оркестратор бойового відновлення (maintenance-вікно, session-gate, pre-restore snapshot, verify, контрольований рестарт, freshness);
- `docs/disaster-recovery.md` §«Pre-adoption recovery» — ручний timescale-aware шлях під легасі `avelren`, доки adoption не завершено.

Чого справді немає — **репетиції**: послідовності «як підняти ізольований
кластер, звідки в ньому беруться ролі, як зібрати DSN, чим саме довести
результат». Вона існувала тільки всередині CI-харнеса
`deploy/restore-integration-test.sh`, який генерує собі compose і не призначений
для бойового хоста. Цей документ закриває саме цю дірку.

---

## 1. Передумови — доступ (premise, не крок)

Виконавець мусить **уже мати**, до початку:

- `root` або `docker`-група на хості (обовʼязково `docker compose`, `psql` — усередині контейнера);
- читання `/opt/avelren` (компоуз, `deploy/`, `db/`);
- доступ до `rclone` конфіга ремоуту (`/root/.config/rclone/rclone.conf`) — **на читання**;
- `sudo` для `docker` і для читання `/opt/avelren/.env` (перевірено на цьому хості). **Процедура не припускає, що оператор — root**: усі звернення до `$WORK` роби через `sudo`, інакше `cd` туди мовчки не спрацює і перевірки пропустяться;
- право створити `/var/lib/avelren-restore-rehearsal`;
- **сім стендових паролів**, які виконавець генерує сам і які **не збігаються з бойовими**. Бойові паролі в цій процедурі не потрібні жодного разу.

Якщо чогось із цього немає — **стоп**, це не «розберемось по ходу».

## 1a. Передумови — стан хоста

Перевірити (read-only), і **не продовжувати**, якщо не сходиться:

```bash
git -C /opt/avelren rev-parse HEAD                 # має бути пін прода (deploy/PROD_PIN)
git -C /opt/avelren status --porcelain             # має бути ПОРОЖНЬО
df -h /var/lib                                     # вільного місця ≥ 3× розміру дампа
docker image inspect avelren-app:latest \
  --format '{{range .Config.Env}}{{println .}}{{end}}' | grep AVELREN_GIT_SHA
```

Останній рядок має показати той самий комміт. Якщо `AVELREN_GIT_SHA` порожній
або інший — образ зібрано не з піна; стенд тоді перевіряє **не той** застосунок.
Це не привід зупинятись, але це треба записати у звіт явно.

> Чому `git status` має бути порожнім: не тому, що це блокує репетицію (не
> блокує), а тому що брудне дерево все одно заблокує `postgres-adopt.sh` пізніше
> — краще виявити зараз. Див. «Clean-worktree invariant» у
> `deploy/postgres-adoption-runbook.md`.

---

## 2. Крок 1 — робочий каталог поза checkout

Усе, що ми створюємо, живе **поза** `/opt/avelren`. Це не стиль, це вимога:
будь-який файл усередині checkout робить дерево брудним і потім відмовляє
adoption.

Два шляхи винесені у змінні — не для краси, а тому що без цього процедура
непереносна, і перший прогін на одноразовій машині падає не через свою хибу
(розділ 12):

| змінна | бойовий хост | одноразова машина |
|---|---|---|
| `STACK` | `/opt/avelren` | шлях до клону репозиторію |
| `WORK` | `/var/lib/avelren-restore-rehearsal` | будь-який каталог поза клоном |

```bash
umask 077
export STACK=/opt/avelren
export WORK=/var/lib/avelren-restore-rehearsal

# 0701 — лише біт проходу: контейнер мусить ПРОЙТИ крізь $WORK до
# migrations-009, але не має права переліку вмісту.
install -d -m 0701 "$WORK"
# 0700 — сюди контейнер не заходить: розшифрований дамп і паролі стенду.
install -d -m 0700 "$WORK/stand" "$WORK/artifact"
```

> **Чому не `0700` на `$WORK`.** Образ `avelren-app` працює під непривілейованим
> uid 10001 (`USER avelren` у `app/Dockerfile`), а процедуру виконує root або
> оператор із sudo. Каталог `0700 root:root` контейнер відкрити не може, і
> `/migrations` усередині виглядає **порожнім** — не помилкою доступу, а
> порожнім каталогом. Крок 9 тоді падає з `міграція 00X записана, але файлу
> нема` ×9, що читається як пошкоджений дамп, хоча дамп цілий.
>
> Знайдено лише на бойовому хості (2026-08-17). Три стенди були зелені, бо
> Windows-ФС мовчки не застосувала `chmod`, і попередження
> `install: cannot change permissions` списали як несуттєве. Урок ширший за цей
> крок: попередження, яке ви пояснили собі, — не те саме, що попередження, яке
> ви перевірили.

---

## 3. Крок 2 — артефакт: забрати, звірити, **прочитати**

```bash
cd "$WORK/artifact"
rclone lsf gdrive-crypt:avelren/daily/ --files-only | sort | tail -5
```

Обрати артефакт (зазвичай останній `avelren-YYYYmmdd-HHMMSS.sql.gz`), забрати
його разом із sidecar:

```bash
NAME=avelren-<stamp>.sql.gz
rclone copyto "gdrive-crypt:avelren/daily/$NAME" "./$NAME"
chmod 0600 "./$NAME"

gzip -t "./$NAME"                 # має мовчати
sha256sum "./$NAME" | tee "./$NAME.local-digest"   # ФІКСУЄМО, не звіряємо
ls -l "./$NAME"
```

> **Sidecar `.sha256` не існує — і це не помилка виконавця.** Розгорнутий на
> проді `/usr/local/sbin/avelren-backup` їх не створює; версія `deploy/backup.sh`
> у репозиторії, яка створює і звіряє sidecar, **не розгорнута** (див. розділ 14).
> Перевірено 2026-08-17: у `daily/`, `weekly/` і `monthly/` — нуль sidecar-файлів.
>
> Тому крок 2 **фіксує** digest завантаженої копії замість того, щоб звіряти її
> з неіснуючим еталоном. Це слабше за sidecar (не ловить пошкодження на боці
> ремоуту), але не вдає доказу, якого немає. Реальний доказ цілісності тут дає
> не хеш, а крок 7: дамп, який завантажився в PostgreSQL із `ON_ERROR_STOP=1` і
> зійшовся з allowlist рушія, пошкодженим бути не може.
>
> Зафіксований digest усе одно потрібен: у звіті він привʼязує всі подальші
> числа до конкретного байтового вмісту.

### 2a. Розвідка дампа — **не пропускати**

Це єдиний крок, який перетворює припущення на вимір. Ми **не знаємо** наперед,
під якою роллю знято бойовий дамп і які ACL він у собі несе; від цього залежать
кроки 8 і 9.

```bash
zcat "./$NAME" | head -30
zcat "./$NAME" | grep -c '^GRANT '
zcat "./$NAME" | grep -oE '\bavelren[a-z_]*\b' | sort -u
# де саме згадана роль — це важливіше за сам факт згадки:
zcat "./$NAME" | grep -n 'bgw_job' | head
```

Записати у звіт:

- версію `pg_dump` і сервера з шапки;
- кількість `GRANT` (нуль — очікувано для схеми 009 до adoption);
- **повний перелік імен ролей**, що зустрічаються в дампі, і **де** саме.

> Навіщо це критично. `restore.sh` виконує дамп із `ON_ERROR_STOP=1`, тож будь-яке
> імʼя ролі в дампі, якого немає в стенді, валить відновлення посеред
> завантаження. І імена ховаються **у двох різних місцях**: у DDL-грантах
> (`GRANT ... TO <роль>`) і **в даних** — колонка `owner` таблиці
> `_timescaledb_config.bgw_job`, де записані власники фонових джобів Timescale
> (compression policy, refresh continuous aggregate).
>
> Друге небезпечніше, бо `grep -c '^GRANT '` його не бачить. Саме так і буде на
> проді: грантів нуль, а імʼя `avelren` присутнє — у даних. Тому перелік ролей
> для кроку 6a береться з **другої** команди, а не з першої.

> **УВАГА: наведене нижче виміряно ДО Gate 11 3B.2 (2026-08-17 14:08 UTC).**
> Adoption змінила рівно те, що тут описано. Артефакти, зняті **після** цієї
> дати, нестимуть ACL з міграції `010`, а прикладні відношення в проді належать
> `avelren_migrator`, не легасі `avelren`.
>
> Що з цього випливає для кроків нижче:
>
> - **крок 2a:** очікувати вже **не нуль** `GRANT`, а повний набір із `010`, і імена всіх шести ролей у ACL — крім згадки легасі `avelren` у `bgw_job`, яка лишається;
> - **крок 6a** — так само обовʼязковий: власник фонових джобів Timescale не змінився;
> - **крок 8** — стає **зайвим**: гранти прийдуть із самого дампа. Виконання його вдруге ідемпотентне й нешкідливе, але вже не потрібне; замість цього перевір, що `avelren_api` читає `checkpoints` **до** нього;
> - **крок 3** (фільтр 001–009) — **без змін**: `schema_migrations` навмисно лишилась на `009`;
> - ownership-передача — без змін: дамп `--no-owner`, відновлення під `avelren_admin`.
>
> Оновити цей блок після 3D, коли `010` буде заштамповано.

**Що саме очікувати в бойовому артефакті — виміряно на проді 2026-08-17
(read-only), стан ДО adoption:**

- дамп знімає **легасі `avelren`** (суперюзер) з `--no-owner`, а не `avelren_backup`;
- на проді **нуль** `table_privileges`, `column_privileges` і default ACL для `avelren_%`-ролей;
- усі 20 прикладних відношень належать легасі `avelren`; слідів 3B.2 немає.

Практичні наслідки, кожен перевіряється командами вище:

1. `GRANT`-ів у дампі має бути **нуль** — і це **не** означає, що крок 6a не потрібен. Імʼя `avelren` майже напевно зʼявиться в даних `bgw_job`; **крок 6a обовʼязковий** (доведено на стенді #3: без нього `exit=3`).
2. `--no-owner` + відновлення під `avelren_admin` ⇒ усе стане admin-owned ⇒ перевірка володіння до handoff пройде.
3. Крок 8 (шар грантів 010) на бойовому артефакті **обовʼязковий, не опційний**: без нього `avelren_api` не має взагалі нічого і smoke падає з `permission denied` (фальсифіковано на стенді #3).

> Для повноти: `deploy/backup.sh` із репозиторію жорстко вимагає роль
> `avelren_backup`, і на схемі 009 `pg_dump -U avelren_backup` падає з
> `permission denied for table schema_migrations`, даючи нуль байтів
> (виміряно на стенді #1). Тобто **той** шлях fail-closed і часткового дампа
> не дає. Але на проді працює не він — див. розділ 14.

---

## 4. Крок 3 — відфільтрований набір міграцій (001–009)

`python -m avelren.schema_verify` (`app/src/avelren/schema_verify.py`,
`verify_history`) звіряє каталог міграцій із таблицею `schema_migrations`
**в обидва боки**: файл без запису — помилка, запис без файлу — помилка, різний
SHA — помилка.

Бойова база стоїть на **009** навмисно (`010` штампується аж на 3D —
`deploy/postgres-adoption-runbook.md`). Якщо змонтувати в стенд повний
`db/migrations`, перевірка гарантовано впаде на:

```
міграція 010_postgresql_least_privilege у файлах, але не записана як застосована
```

Це не обхід перевірки: `verify()` спроєктовано під частковий набір — контракт
фільтрується за фактично записаними версіями (докстрінг `verify()` це прямо
описує). Ми даємо йому каталог, який відповідає стану бази.

```bash
SRC="$STACK/db/migrations"
DST="$WORK/migrations-009"

# 0755/0644 — каталог читає контейнер під uid 10001. Секретів тут немає:
# це ті самі файли, що лежать у git.
install -d -m 0755 "$DST"
cp -p "$SRC"/00*.sql "$DST/"      # 00* бере 001–009 і НЕ бере 010
chmod 0644 "$DST"/*.sql

# байт-у-байт: контрольні суми рахуються по тексту файлу
( cd "$SRC" && sha256sum 00[1-9]_*.sql ) > /tmp/src.sums
( cd "$DST" && sha256sum -c /tmp/src.sums )   # усе має бути OK
ls "$DST"                                     # рівно 9 файлів, без 010
rm -f /tmp/src.sums
```

Одразу довести, що контейнер їх бачить, — інакше помилка спливе аж на кроці 9
й виглядатиме як пошкоджений дамп:

```bash
docker compose -f "$WORK/stand/compose.yml" -p avelren-rv3-86d3534 \
  run --rm --no-deps -T migrate ls /migrations </dev/null    # 9 файлів
```

І перевірити, що закрите лишилось закритим:

```bash
docker compose -f "$WORK/stand/compose.yml" -p avelren-rv3-86d3534 \
  run --rm --no-deps -T -v "$WORK:/w:ro" migrate ls /w/artifact </dev/null
# має бути Permission denied
```

**Якщо після кроку 9 виявиться, що бойова база вже на 010** — тоді копіювати
треба всі десять, а крок 8 пропустити. Перевірити фактичну версію можна вже
після відновлення (крок 7 виводить лічильники; версію дає
`SELECT max(version) FROM schema_migrations`).

---

## 5. Крок 4 — compose стенду

Записати як `$WORK/stand/compose.yml`:

```yaml
# Стенд репетиції відновлення. НЕ бойовий compose.
# Каталог проєкту для Compose = каталог цього файлу, тому тут НЕ МОЖЕ
# випадково підхопитись /opt/avelren/.env з бойовими DSN.
name: avelren-rv3-86d3534

services:
  db:
    # Той самий digest, що й у бойовому docker-compose.yml — інакше
    # репетиція перевіряє інший PostgreSQL.
    image: timescale/timescaledb:2.17.2-pg16@sha256:4e459e217f00cbb09920c34d245501e63427e6767a495de57ce76823ff280f12
    # Стеля нижча за бойову: стенд не має права підʼїсти памʼять у прода.
    mem_limit: 768m
    cpus: 1.0
    environment:
      POSTGRES_USER: avelren_admin
      POSTGRES_PASSWORD: ${STAND_ADMIN_PASSWORD:?stand admin password missing}
      POSTGRES_DB: postgres
      # Маркер існує ЛИШЕ у стендовому .env. Крок 5 доводить ним, що
      # контейнер читає стендове оточення, а не бойове.
      AVELREN_STAND_GUARD: ${AVELREN_STAND_GUARD:?stand env-file not loaded}
    volumes:
      - stand_db:/var/lib/postgresql/data
      # checkout лише на читання: bootstrap-скрипту потрібні db/security/*.sql
      - ${STACK:?STACK not exported}:/workspace:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U avelren_admin -d postgres"]
      interval: 2s
      timeout: 3s
      retries: 30
    # Портів назовні НЕМАЄ навмисно: стенд недосяжний ні з мережі, ні з
    # бойового проєкту (інший Compose-проєкт → інша мережа).

  # Обидва сервіси існують тільки заради `restore-verify.sh`, який запускає їх
  # як `run --rm --no-deps` з підміненою командою (перевірено: команда
  # підставляється на місці виклику, тому `command:` тут — лише заглушка,
  # але сервіси мусять бути описані обидва).
  #
  # На бойовому хості беремо ГОТОВИЙ образ і НЕ збираємо: `build:` перезаписав
  # би тег avelren-app:latest, з якого прод підніметься наступного разу.
  # На одноразовій машині такого тега немає — див. розділ 12.
  migrate:
    image: ${STAND_APP_IMAGE:?STAND_APP_IMAGE not exported}
    command: ["python", "-m", "avelren.migrate"]
    mem_limit: 256m
    cpus: 0.5
    volumes:
      - ${WORK:?WORK not exported}/migrations-009:/migrations:ro

  api:
    image: ${STAND_APP_IMAGE:?STAND_APP_IMAGE not exported}
    command: ["python", "-c", "print('stand api placeholder')"]
    mem_limit: 512m
    cpus: 0.5

volumes:
  stand_db:
```

### Змінні стенду — через оточення, а не через `.env`

Записати `$WORK/stand/stand.env`, режим `0600`:

```
STACK=/opt/avelren
WORK=/var/lib/avelren-restore-rehearsal
STAND_APP_IMAGE=avelren-app:latest
AVELREN_STAND_GUARD=stand
STAND_ADMIN_PASSWORD=<стендовий, згенерований щойно>
STAND_MIGRATOR_PASSWORD=<стендовий>
STAND_BACKUP_PASSWORD=<стендовий>
STAND_COLLECTOR_PASSWORD=<стендовий>
STAND_NOTIFIER_PASSWORD=<стендовий>
STAND_WATCHDOG_PASSWORD=<стендовий>
STAND_API_PASSWORD=<стендовий>
```

```bash
chmod 0600 "$WORK/stand/stand.env"
```

І **в кожній сесії, перед кожною командою з наступних кроків**:

```bash
set -a; . "$WORK/stand/stand.env"; set +a
```

Паролі генерувати лише з `[A-Za-z0-9]` (`openssl rand -hex 24`): вони йдуть
у DSN без екранування, і спецсимвол мовчки зіпсує URI.

> **Чому саме через оточення, а не через `.env` у каталозі стенду.**
> `deploy/restore.sh` і `deploy/restore-verify.sh` мають власну обгортку
> `compose()`, яка передає лише `-f` і `-p` — **без** `--project-directory`
> і **без** `--env-file`. При цьому рушій (`restore-engine.lib.sh`) перед
> викликом робить `cd "$AVELREN_STACK_DIR"`, тобто в `/opt/avelren`. Куди саме
> Compose піде по `.env` у такій конфігурації — у каталог compose-файлу чи в
> поточний, — залежить від версії; покладатись на це не можна, бо в поточному
> лежить **бойовий** `.env`.
>
> Значення з оточення шелу мають вищий пріоритет за будь-який `.env` у будь-якій
> версії Compose. Тому ми не вгадуємо — ми експортуємо. А `:?` у compose-файлі
> робить помилку гучною: якщо змінні не експортовані, Compose зупиниться з
> явним повідомленням замість того, щоб мовчки підставити щось із бойового
> `.env`. У `/opt/avelren/.env` ключів `AVELREN_STAND_GUARD` і
> `STAND_ADMIN_PASSWORD` немає — отже, підставити нема чого, і сценарій
> «стенд тихо взяв бойові значення» структурно неможливий.

Перевірити модель до будь-якого запуску:

```bash
cd "$WORK/stand"
docker compose -f compose.yml -p avelren-rv3-86d3534 config >/dev/null
```

Має пройти без попереджень про порожні змінні.

---

## 6. Крок 5 — підняти db і **довести ізоляцію**

```bash
cd "$WORK/stand"
docker compose -f compose.yml -p avelren-rv3-86d3534 up --detach --wait db
```

Три докази поспіль (усі мають пройти):

```bash
C="docker compose -f compose.yml -p avelren-rv3-86d3534"

# 1. контейнер читає стендове оточення
$C exec -T db sh -c '[ "$AVELREN_STAND_GUARD" = stand ]' && echo GUARD-OK

# 2. бойових змінних у ньому немає
$C exec -T db sh -c '[ -z "$ECHERHA_DEVICE_ID" ] && [ -z "$AVELREN_API_DSN" ]' && echo NO-PROD-ENV

# 3. бойові контейнери не зачеплені (жоден не перестворено)
docker ps --filter label=com.docker.compose.project=avelren \
          --format '{{.Names}}\t{{.Status}}'
```

Третій вивід має показати ті самі uptime, що й до початку. Якщо якийсь
бойовий контейнер має вік у секунди — **негайно стоп**: це рецидив інциденту
2026-08-14.

---

## 7. Крок 6 — ролі у стенді

`postgres-bootstrap.sh` виконуємо **всередині** контейнера db: там є `psql`, і
там же змонтований checkout.

```bash
cd "$WORK/stand"
set -a; . ./stand.env; set +a

AVELREN_ADMIN_DSN="postgresql://avelren_admin:$STAND_ADMIN_PASSWORD@localhost:5432/postgres" \
AVELREN_ADMIN_PASSWORD="$STAND_ADMIN_PASSWORD" \
AVELREN_MIGRATOR_PASSWORD="$STAND_MIGRATOR_PASSWORD" \
AVELREN_BACKUP_PASSWORD="$STAND_BACKUP_PASSWORD" \
AVELREN_COLLECTOR_PASSWORD="$STAND_COLLECTOR_PASSWORD" \
AVELREN_NOTIFIER_PASSWORD="$STAND_NOTIFIER_PASSWORD" \
AVELREN_WATCHDOG_PASSWORD="$STAND_WATCHDOG_PASSWORD" \
AVELREN_API_PASSWORD="$STAND_API_PASSWORD" \
docker compose -f compose.yml -p avelren-rv3-86d3534 exec -T \
  -e AVELREN_ADMIN_DSN -e AVELREN_ADMIN_PASSWORD \
  -e AVELREN_MIGRATOR_PASSWORD -e AVELREN_BACKUP_PASSWORD \
  -e AVELREN_COLLECTOR_PASSWORD -e AVELREN_NOTIFIER_PASSWORD \
  -e AVELREN_WATCHDOG_PASSWORD -e AVELREN_API_PASSWORD \
  -e AVELREN_DB_NAME=restore_test -e AVELREN_TEST_DB=1 \
  db bash /workspace/deploy/postgres-bootstrap.sh fresh
```

Очікуваний хвіст виводу: `migrate_handoff`, далі
`postgres bootstrap complete: fresh`.

Що саме тут відбувається і чому це та сама **топологія володіння**, про яку
йдеться в `restore-engine.lib.sh`:

- `db/security/bootstrap.sql` створює 7 ролей; `avelren_admin` — `LOGIN SUPERUSER`, решта — `NOINHERIT NOBYPASSRLS`, **без жодного membership** між собою (скрипт це ще й перевіряє й падає, якщо membership зʼявився);
- `create_database` створює `restore_test` з `OWNER avelren_admin`;
- `provision_extension` ставить `timescaledb` **від імені `avelren_admin`** → власник розширення `avelren_admin`;
- `apply_acl` робить власником бази і схеми `public` `avelren_admin`, знімає права з `PUBLIC` і видає `CONNECT`/`USAGE` семи ролям;
- `verify_owners` падає, якщо власник бази, схеми або розширення — не `avelren_admin`.

Саме ці три власники — база, `public`, `timescaledb` — і є та передумова, без
якої `restore_application_owners` кидає виняток. Стенд не «має сім ролей»;
стенд **відтворює топологію**.

> Крок 7 зараз видалить і створить `restore_test` заново. Це не марна робота:
> `createdb`/`CREATE EXTENSION` рушій робить теж від `avelren_admin`, тож
> топологія зберігається, а ролі й їхні паролі — те, заради чого цей крок
> існує, — переживають перестворення бази.

### 6a. Легасі роль — на бойовому артефакті обовʼязково

Якщо крок 2a показав у дампі імʼя `avelren` (без суфікса) — а на бойовому
артефакті він його покаже — створити роль у стенді **до** відновлення:

```bash
PGPASSWORD="$STAND_ADMIN_PASSWORD" \
docker compose -f compose.yml -p avelren-rv3-86d3534 exec -T -e PGPASSWORD db \
  psql -U avelren_admin -d postgres -v ON_ERROR_STOP=1 -c \
  "DO \$\$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='avelren')
   THEN CREATE ROLE avelren NOLOGIN; END IF; END \$\$;"
```

> **Причина — не гранти.** Тут раніше було написано «інакше
> `GRANT ... TO avelren` завалить завантаження». Це хибно: грантів у бойовому
> дампі нуль. Справжня причина — **дані**: у `COPY _timescaledb_config.bgw_job`
> колонка `owner` містить імʼя ролі-власника фонових джобів Timescale. Без цієї
> ролі завантаження падає:
>
> ```
> CONTEXT:  COPY bgw_job, line 1, column owner: "avelren"
> primary restore failure (exit=3); attempting timescaledb_post_restore
> timescaledb_post_restore cleanup succeeded after primary failure
> ```
>
> Різниця не академічна: оператор, який прочитав би стару причину і побачив
> нуль грантів у кроці 2a, обґрунтовано вирішив би, що крок непотрібен — і
> зловив би `exit=3` посеред бойового вікна. Доведено обома боками на
> стенді #3: без ролі падає, з роллю проходить 7→9 повністю.

`NOLOGIN` навмисно: роль потрібна лише як носій імені власника, підключатись
під нею ніхто не має. Наслідок — фонові джоби Timescale у стенді не
запускатимуться (власник без LOGIN). Для перевірки це байдуже; шукати причину
не треба.

---

## 8. Крок 7 — власне відновлення

```bash
cd "$WORK/stand"
AVELREN_STACK_DIR="$STACK" \
AVELREN_COMPOSE_FILE="$WORK/stand/compose.yml" \
AVELREN_COMPOSE_PROJECT=avelren-rv3-86d3534 \
AVELREN_DB_SERVICE=db \
AVELREN_ADMIN_PASSWORD="$STAND_ADMIN_PASSWORD" \
bash "$STACK/deploy/restore.sh" \
  "$WORK/artifact/$NAME" --target restore_test
```

`restore.sh` — публічний CLI, який **структурно** вміє тільки `restore_test`:
будь-яка інша ціль отримує «direct production restore заборонений». Тобто ця
команда не може зачепити `avelren` навіть через одруківку.

Послідовність рушія (`deploy/restore-engine.lib.sh`): `dropdb --if-exists` →
`createdb` → `CREATE EXTENSION timescaledb` → `timescaledb_pre_restore()` →
`gunzip -c … | psql` → `timescaledb_post_restore()` → **ownership handoff** →
лічильники.

Очікуваний хвіст — таблиця з чотирма числами:

```
 observations | checkpoints | hypertables | aggregates
```

Записати їх у звіт. `observations` і `checkpoints` мають бути близькі до
бойових; `hypertables` = 1, `aggregates` = 1.

Одразу після цього зафіксувати версію схеми — вона визначає, чи правильно ми
відфільтрували міграції на кроці 3:

```bash
PGPASSWORD="$STAND_ADMIN_PASSWORD" \
docker compose -f compose.yml -p avelren-rv3-86d3534 exec -T -e PGPASSWORD db \
  psql -U avelren_admin -d restore_test -At -c \
  'SELECT max(version) FROM schema_migrations;'
```

Очікується `009_observability`. Якщо `010_postgresql_least_privilege` —
повернутись до кроку 3, покласти в `migrations-009` усі десять файлів
(перейменувавши каталог), і **пропустити крок 8**.

---

## 9. Крок 8 — шар грантів 010 (**лише на стенді**)

Причина, чому цей крок існує, — конкретна й перевірена по коду:

- рушій передає володіння прикладними обʼєктами ролі `avelren_migrator`, тому `schema_verify` під `avelren_migrator` працює як власник;
- а `avelren_api` після відновлення дампа схеми **009 не має жодного права** на прикладні таблиці — усі гранти для рантайм-ролей живуть у міграції `010`;
- `restore_smoke` робить `POST /devices`, тобто `INSERT` у `devices`. Без 010 він падає з `permission denied`, і це буде **хибний червоний**: артефакт цілий, бракує шару прав, якого в бойовій базі поки й немає.

```bash
PGPASSWORD="$STAND_ADMIN_PASSWORD" \
docker compose -f compose.yml -p avelren-rv3-86d3534 exec -T -e PGPASSWORD db \
  psql -U avelren_admin -d restore_test -v ON_ERROR_STOP=1 \
  -f /workspace/db/migrations/010_postgresql_least_privilege.sql
```

Виконує `avelren_admin`, він `SUPERUSER` — тому має право видавати гранти на
обʼєкти, які вже належать `avelren_migrator`.

**Це `psql -f`, а не `python -m avelren.migrate`.** Різниця принципова:
`migrate` записав би `010` у `schema_migrations`, і тоді історія розійшлася б
із каталогом `migrations-009`. Ми навмисно накладаємо гранти **без штампа** —
рівно та комбінація, яка робить стенд придатним для перевірки, не спотворивши
історію.

Що це означає для інтерпретації результату: крок 9 доводить, що
**дані й схема цілі, а застосунок на них працює під набором прав, який
принесе 3B.2**. Він **не** доводить, що поточна бойова база вже має ці права —
вона їх і не має, за проєктом.

---

## 10. Крок 9 — верифікація інструментами проєкту

```bash
cd "$WORK/stand"
AVELREN_STACK_DIR="$STACK" \
AVELREN_COMPOSE_FILE="$WORK/stand/compose.yml" \
AVELREN_COMPOSE_PROJECT=avelren-rv3-86d3534 \
AVELREN_VERIFY_SCHEMA_SERVICE=migrate \
AVELREN_VERIFY_API_SERVICE=api \
AVELREN_VERIFY_MIGRATIONS_DIR=/migrations \
AVELREN_VERIFY_MIGRATOR_DSN="postgresql://avelren_migrator:$STAND_MIGRATOR_PASSWORD@db:5432/restore_test" \
AVELREN_VERIFY_API_DSN="postgresql://avelren_api:$STAND_API_PASSWORD@db:5432/restore_test" \
bash "$STACK/deploy/restore-verify.sh" restore_test
```

Хост у DSN — `db`, імʼя сервісу: контейнери `run --rm` живуть у мережі того ж
Compose-проєкту.

> Паролі стенду підставляються в URI без екранування, тож генерувати їх треба
> лише з `[A-Za-z0-9]` (наприклад `openssl rand -hex 24`). Пароль зі
> спецсимволом мовчки зіпсує DSN, і помилка виглядатиме як «роль не існує».

Очікуваний вивід:

```
>>> schema verification against restore_test
>>> disposable API smoke against restore_test
restore-verify OK: restore_test
```

Що при цьому реально сталося:

- `restore-verify.sh` відмовився б працювати, якби `AVELREN_COMPOSE_PROJECT` був порожній або дорівнював `avelren` — це структурний запобіжник після 2026-08-14, і він тут спрацьовує на нашу користь;
- обидва запуски йдуть із `--no-deps`, тому `db` не переузгоджується;
- `schema_verify` звіряє історію міграцій (перелік + SHA кожного файлу) і фізичний контракт: таблиці, колонки, часткові унікальні індекси разом із їхніми предикатами, іменовані constraints, гіпертаблиці, continuous aggregates;
- `restore_smoke` піднімає справжній FastAPI-застосунок і проходить `GET /health` (з явною вимогою `last_observation != null`), `401` без авторизації, `POST /devices` → **201**, і аж тоді `GET /active-alerts`
з отриманою парою → `200`. Перед усім цим `restore_identity` звіряє `current_database`, `current_user`, `session_user` і `system_user` — підмінити ціль параметрами URI не вийде.

---

## 11. Крок 10 — прибирання

```bash
cd "$WORK/stand"
docker compose -f compose.yml -p avelren-rv3-86d3534 down --volumes --remove-orphans

# розшифрований дамп містить fcm_token і secret_hash усіх пристроїв
rm -f "$WORK/artifact/$NAME" "$WORK/artifact/$NAME.sha256"

docker volume ls | grep avelren-rv3     # має бути порожньо
docker ps -a   | grep avelren-rv3       # має бути порожньо
git -C "$STACK" status --porcelain      # має бути порожньо
```

`--volumes` тут не косметика: без нього том `stand_db` лишається на диску з
повною копією бойових даних.

Далі — те, що лишається на диску після «прибирання», якщо про нього не сказати
прямо:

```bash
shred -u "$WORK/stand/stand.env"   # СІМ стендових паролів
rm -rf "$WORK/migrations-009"      # інакше каталог переживе стенд і всіх забуде
ls -la "$WORK" "$WORK/stand"       # має лишитись тільки compose.yml
```

> **Це `stand.env`, а не `.env`.** Файл `.env` у каталозі стенду навмисно
> **не створюється** — саме щоб Compose не мав що звідти підхопити (крок 4).
> `shred -u` на неіснуючому файлі лише поскаржиться в stderr і поверне
> ненульовий код, а сім паролів тихо лишаться лежати. Знайдено прогоном
> стенду #1.

---

## 12. Порядок: одноразовий стенд → бойовий хост

1. **Спершу** — на одноразовій машині (де `docker compose` є, а бойових контейнерів немає за визначенням). Там дозволено помилятись.
2. Артефакт узяти **малий і синтетичний**: підняти джерельну БД тими самими скриптами і зняти з неї дамп. Мета першого прогону — виловити помилки в тексті, а не перевірити бойові дані.
3. Записати кожне розходження між текстом і реальністю. Виправити документ.
4. **Тільки потім** — на бойовому хості з бойовим артефактом.

### 12a. Що змінюється на одноразовій машині

Три відмінності, і всі три — у `stand.env`, не в тексті процедури:

```
STACK=<шлях до клону репозиторію>
WORK=<каталог поза клоном>
STAND_APP_IMAGE=avelren-app:stand
```

Образу `avelren-app:latest` на такій машині не існує — його треба зібрати
**під окремим тегом**, щоб не плутати з бойовим:

```bash
docker build -t avelren-app:stand "$STACK/app"
```

Крок 1a (`docker image inspect avelren-app:latest`) там пропускається: він
перевіряє відповідність бойового образу піну прода, а локально це безпредметно.

### 12b. Джерельна БД для синтетичного артефакта

`postgres-bootstrap.sh fresh` створює ролі, базу, розширення й ACL — але
**міграцій не застосовує**. `migrate_handoff` у його виводі — це буквально
`printf`, а не дія. Щоб мати з чого зняти дамп, міграції треба застосувати
окремо:

```bash
docker compose -f compose.yml -p <проєкт-стенду> run --rm --no-deps -T \
  -e DATABASE_URL="postgresql://avelren_migrator:$STAND_MIGRATOR_PASSWORD@db:5432/<джерельна_БД>" \
  migrate python -m avelren.migrate /migrations
```

На бойовому прогоні цього кроку **немає** — там схема приходить із дампа.

### 12c. Прогони — що кожен доводив (2026-08-17)

| стенд | питання | результат |
|---|---|---|
| **прод** | чи відновлюється **бойовий** артефакт | **зелений**; знайдено дефект прав доступу, який три стенди пропустили |
| #1 | чи процедура взагалі виконувана | зелений; знайдено 3 дефекти тексту (паролі не прибирались, непереносність, `201` замість `200`) |
| #2 | чи виправлена редакція працює | зелений; `:?`-запобіжники фальсифіковано по одній змінній — усі пʼять відмовляють з точною локацією |
| #3 | чи достатньо кроку 8 на артефакті **бойового класу** (0 `GRANT`) | зелений; **знайдено `bgw_job`** — крок 6a обовʼязковий, причина в документі була хибна |

Стенд #3 відповів на два питання, задля яких і затримувався бойовий GO:

- **крок 8 наодинці достатній.** На артефакті з нулем `GRANT`/`REVOKE` крок 7 завантажився (242/2/1/1), 010 наклався `rc=0`, після нього `avelren_api` читає `checkpoints`.
- **`USAGE` на `public` є, і це вимір, а не теорія.** `has_schema_privilege('avelren_api','public','USAGE')` = `t`; джерело — успадкування від `PUBLIC` у базі, яку рушій створює наново після `dropdb`. Доповнювати 010 не треба.

Крок 8 фальсифіковано червоним навмисно: між 7 і 8 `avelren_api` дає
`ERROR: permission denied for table checkpoints`. Крок не декоративний.

### 12d. Бойовий прогін 2026-08-17 ~11:10–11:30 UTC

Артефакт `avelren-20260817-032103.sql.gz`, 2 391 593 байти, `gzip -t OK`,
digest `84af8c5df6fb9fb8e424b5a553cc21bdf47d6b35e43cdedaf5383e0fb692b8e2`,
sidecar відсутній (issue #93).

**Відповідь, заради якої репетиція існувала:** `allowlist mismatch` **не
сталося**. Відновлення дало 522 082 observations, 38 checkpoints,
1 hypertable, 1 aggregate. Бойове відновлення сьогодні спрацювало б.

Незалежна перевірка повноти дампа проти живої бази в той самий момент:
540 246 observations, 38 checkpoints, останнє о 11:20:03Z. Різниця 18 164 при
479 хв × 38 КПП = 18 202 — розбіжність рівно 38, тобто один цикл опитування на
межі інтервалу. Дамп повний, збирач без пропусків.

Крок 2a: 0 `GRANT`, 0 `REVOKE`, рівно дві згадки `avelren` — обидві в даних
`bgw_job`. Крок 6a знадобився, саме з цієї причини.

Крок 8 фальсифіковано на реальних даних: до нього `avelren_api` →
`permission denied for table checkpoints`, після — читає. Історія лишилась
`009_observability` / 9 записів. Крок 9: `схема узгоджена: 9 міграцій,
контракт цілий`, `restore-verify OK: restore_test`.

Прод не зачеплено: 6/6 контейнерів із незмінними `CreatedAt` і uptime,
`avelren-db-1` id + `StartedAt` (`3428ddde…` / `2026-08-14T06:23:59.222Z`)
побітово ті самі до підйому стенду, після нього й після відновлення;
`git status` порожній тричі; health ok. Жодне стоп-правило не спрацювало.
Розшифрований дамп і `stand.env` знищено `shred` на кроці 10.

Зафіксовані відхилення в передумовах: `deploy/PROD_PIN` = `c84f531` при HEAD
`86d3534` (PR #92 відкритий); `AVELREN_GIT_SHA` в образі порожній — тобто
відповідність бойового образу піну **недоказувана**.

### 12e. Деталі прогону #1

Фінал зелений:

```
schema_verify: схема узгоджена: 9 міграцій, контракт цілий
restore_smoke: prod-guard, health+observations, auth-контур, devices/secret, protected-запит
restore-verify OK: restore_test
```

Відновлення дало 242 спостереження, 2 КПП, 1 гіпертаблицю, 1 агрегат — точно
як у джерелі; allowlist рушія зійшовся, передача володіння відпрацювала.
Крок 8 наклав 010 без штампа: історія лишилась `009_observability`, 9 записів.
Прибирання чисте.

Додатково — **фальсифікація запобіжників** (процедура цього не вимагала, але
перед бойовим прогоном це головне): порожній `AVELREN_COMPOSE_PROJECT` →
`REFUSED`, `rc=2`; проєкт `avelren` → `REFUSED`, `rc=2`;
`restore.sh --target avelren` → `ВІДМОВА: direct production restore
заборонений`. Усі три відмовляють правильно.

Дрібне: образ на Python 3.14 видає `StarletteDeprecationWarning` (httpx у
`starlette.testclient`) на шляху `restore_smoke`. У проді не проявляється —
`restore_smoke` там не запускається.

---

## 13. Коли червоне — що це означає

| Повідомлення | Причина | Що робити |
|---|---|---|
| `restore application relation allowlist mismatch: unexpected public.X` | у бойовій базі є обʼєкт, якого нема в allowlist рушія | **Справжня знахідка.** Те саме завалило б і бойове відновлення. Треба узгодити обидва блоки `expected(...)` у `restore-engine.lib.sh` і `_TABLES_V` у `schema_verify.py`; дрейф ловить `deploy/restore-allowlist-contract-test.py` |
| `… mismatch: missing public.X` | дамп неповний, або в ролі дампу не було `SELECT` на X | **Найгірший результат із можливих**: бекап мовчки неповний. Зупинити все, розібратись із правами `avelren_backup` |
| `restored application relations must be owned by avelren_admin before handoff` | дамп знято не з `--no-owner`, або відновлює не `avelren_admin` | звірити крок 2a і `AVELREN_ADMIN_PASSWORD` |
| `timescaledb extension owner must remain avelren_admin` | розширення поставили не від `avelren_admin` | крок 6 виконано не повністю (`provision_extension`) |
| `міграція 010… у файлах, але не записана як застосована` | крок 3 пропущено або каталог не той | перезібрати `migrations-009` |
| `міграція NNN: SHA у БД не збігається з файлом` | файл міграції редагували **після** застосування | окремий інцидент; репетицію зупинити |
| `permission denied for table devices` у smoke | крок 8 пропущено | накласти 010 і повторити крок 9 |
| `REFUSED: disposable restore verification requires an explicit non-production Compose project` | не задано `AVELREN_COMPOSE_PROJECT` | так і має бути; задати проєкт стенду |
| `REFUSED: restore verification must not run in the production Compose project` | проєкт назвали `avelren` | перейменувати; це запобіжник 2026-08-14 |
| `ВІДМОВА: direct production restore заборонений` | `--target` не `restore_test` | так і має бути |
| `/health повертає last_observation=null` | схема ціла, даних нема | дамп порожній або відновились лише структури |
| `primary restore failure … timescaledb_post_restore cleanup succeeded` | дамп не завантажився, але Timescale прибрано коректно | дивитись першопричину вище в логу; сам cleanup спрацював правильно |
| `міграція 00X записана, але файлу нема (чужа/майбутня версія)` ×9 | `/migrations` у контейнері **порожній**: каталог `$WORK` недоступний для uid 10001 | не дамп. Виправити режими (`$WORK` → `0701`, `migrations-009` → `0755`, файли `0644`) і повторити **лише крок 9** — відновлення переробляти не треба |
| `CONTEXT: COPY bgw_job, line N, column owner: "<роль>"`, далі `exit=3` | у стенді немає ролі-власника фонових джобів Timescale | крок 6a пропущено. Створити роль, повторити крок 7 з початку |
| скрипт «обривається» після першого ж `compose exec -T` | `-T` пробрасує stdin, і `exec` зʼїдає решту скрипта, який bash читає з того самого stdin | додати `</dev/null` до кожного `compose exec -T`, який не має отримувати вхід (усі, крім завантаження дампа). Знайдено на проді 2026-08-17 |

---

## 14. Дрейф бекап-скрипта — виміряно 2026-08-17

Питання, з якого це почалось: `backup.sh:36` вимагає роль `avelren_backup`,
гранти для неї вводить лише `010`, прод стоїть на `009` — а нічний прогін
03:21Z успішний і дав 2 391 593 байти. Було три гіпотези: ручна видача прав,
атрибут ролі, залишок форварду 14 серпня.

**Спростовані всі три.** Прод read-only показав: `avelren_backup` не
`SUPERUSER` і не `BYPASSRLS`; членств між `avelren%`-ролями нуль; грантів
нема взагалі. Зокрема це означає, що **inverse-rollback 14 серпня знявся
повністю** — канонічний граф цілий.

Справжня причина в іншому шарі. Systemd-юніт запускає не `deploy/backup.sh` із
репозиторію, а окремий `/usr/local/sbin/avelren-backup` (root:root 750, від
7 серпня), який знімає дамп під легасі `avelren`. Роль `avelren_backup` у
бойовому шляху бекапу **не задіяна взагалі**.

Чого немає в розгорнутій версії проти репозиторної:

| | репо `deploy/backup.sh` | розгорнутий `/usr/local/sbin/avelren-backup` |
|---|---|---|
| роль | `avelren_backup` (fail, якщо інша) | легасі `avelren` |
| sidecar `.sha256` | створює і звіряє через `rclone cat` | **не створює** |
| `gzip -t` після дампа | так | ні (лише «≥ 10240 байт») |
| звірка digest/розміру після відправки | так | ні |
| гарантія, що ремоут типу `crypt` | preflight, fail-closed | **не перевіряє** |

Чому це важливо саме тут: `AVELREN_RECOVERY_PREFLIGHT_FILE` містить рядок
`backup_recovery=PASS`, і поки не ясно, що саме він засвідчує — репозиторний
скрипт чи розгорнутий, — це підпис під припущенням. Цей розділ прибирає
припущення: підписувати треба знаючи, що працює **розгорнута** версія з
переліченими послабленнями.

Що це **не** ставить під сумнів: бекапи здорові й ідуть. 16.08 — неділя
(`DOW=7`), тож артефакт пішов у `weekly/`, пропуску немає. Розміри ростуть
правдоподібно (1.65 МБ 14.08 → 2.39 МБ 17.08). Відсутність `monthly/`
пояснюється календарем, а не дефектом: скрипт встановлено 7 серпня, першого
числа з того часу ще не було — перша можливість буде 1 вересня.

Виправлення дрейфу — окреме завдання, не частина цієї процедури.

---

## 15. Що з цим документом далі

Після успішного прогону **на бойовому хості** — скласти його в
`docs/disaster-recovery.md` окремим розділом «Restore rehearsal», з фактичними
числами прогону. Доти документ живе окремо: складати в канонічний runbook
процедуру, яку ще ніхто не виконав, — це рівно та помилка, через яку B2
провалився минулого разу.

Далі за планом — B3 (evidence), і лише потім 3B.2.
