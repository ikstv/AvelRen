# Картка вікна 3B.2 — продова adoption володіння й ACL

> **Виконано 2026-08-17 14:07–14:08 UTC, `exit 0`, `stage=committed`.**
> Ця редакція — та, за якою вікно пройшло. Три попередні спроби провалились на
> неповному оточенні; розділи 2.6a, 4.1 і 4.2 — саме те, що це закрило.
>
> Результат, перевірений виміром, а не логом: володіння 20 обʼєктів →
> `avelren_migrator`; ACL роздано (api 18, backup 14, collector 27,
> migrator 98, notifier 8, watchdog 6); схема лишилась `009_observability`;
> легасі `avelren` `SUPERUSER+LOGIN` недоторканий; `db` не перестворено;
> `migrate` не запускався; гейт після коміту — **25 passed** проти 22 failed у
> сухій перевірці. Простій клієнтів ~31 с.

> Це **не** авторизація і не заміна `deploy/postgres-adoption-runbook.md`.
> Рунбук пояснює *чому*; ця картка — точний контракт запуску, виведений із
> `deploy/postgres-adopt.sh` на комміті прода, плюс правила зупинки.
>
> Одна команда тут **мутує бойову базу**. Усе до неї — read-only.

---

## 0. Що робить і чого не робить

**Робить:** переносить володіння прикладними обʼєктами на `avelren_migrator`,
застосовує ACL із міграції `010`, лишає легасі `avelren` `SUPERUSER+LOGIN`
недоторканим, вертає клієнтів на **незмінному** легасі DSN.

**Не робить:** не створює ролей (це 3B.1, уже зроблено), не запускає `migrate`,
не штампує `010` — `schema_migrations` лишається на `009` **за проєктом**, не
перемикає DSN, не чіпає `.env`.

Після успіху — `HARD STOP`. Наступний етап (3C) не існує як продовий режим і
не запускається випадково.

---

## 1. Передумови — доступ

**Вікно запускається під `root`, і це не стиль, а арифметика.** `adopt.sh`
звіряє власника preflight-файла, токена й раннера з `id -u` того, хто запускає.
На хості вони `root`-owned (`600`, `600`, `700`), тож рівність виконується лише
під root — а інакше й неможливо: `docker` потребує sudo, `.env` читається лише
root, раннер `700 root` для `averlenadmin` невиконуваний.

- `root` або sudo на бойовому хості;
- `/opt/avelren` — чекаут на комміті прода, **чисте** дерево;
- `.env` з бойовими DSN — на читання;
- три файли, кожен зі своїми правами (розділ 2).

Нічого з цього не «добудовується по ходу». Немає — стоп.

---

## 2. Preflight — усе read-only, усе перевіряється, нічого не припускається

### 2.1 Комміт і дерево

```bash
COMMIT=$(git -C /opt/avelren rev-parse HEAD); echo "$COMMIT"
git -C /opt/avelren status --porcelain          # МУСИТЬ бути порожньо
```

`adopt.sh` порівнює `AVELREN_EXPECTED_COMMIT` із `git rev-parse HEAD` **точно**
(40 hex, нижній регістр) і відмовляє на `exact commit mismatch`. Будь-який
неврахований файл у чекауті → `worktree is dirty`.

### 2.2 Preflight-файл

```bash
PREFLIGHT=/var/lib/avelren-adoption/recovery-preflight-<stamp>.txt
stat -c '%a %u %F' "$PREFLIGHT"    # 400 або 600, uid = id -u, regular file
wc -l -c "$PREFLIGHT"              # 3 рядки
grep -Fxq "exact_commit=$COMMIT" "$PREFLIGHT" && echo PREFLIGHT-COMMIT-OK
```

Скрипт вимагає **рівно** три рядки і звіряє третій із `EXPECTED_COMMIT`
(`recovery preflight commit mismatch`). Файл — не симлінк, власник = той, хто
запускає adoption.

### 2.3 Токен-файл

```bash
TOKEN=/var/lib/avelren-adoption/prod-adoption-token
stat -c '%a %u' "$TOKEN"           # 400 або 600, uid = id -u
```

Вміст мусить бути **точно** `AVELREN-POSTGRES-ADOPTION-PROD`. Токен читається
з файлу, ніколи з argv — не передавай його в командному рядку.

### 2.4 Раннер гейта

```bash
RUNNER=/usr/local/sbin/avelren-privilege-gate     # звір фактичний шлях
stat -c '%a %u %F' "$RUNNER"       # 500 або 700, uid = id -u, regular, не симлінк
test -x "$RUNNER" && echo RUNNER-EXECUTABLE
```

**І свіжість образу** — те, що завалило 14 серпня і мало не завалило зараз:

```bash
sudo docker run --rm --network none --entrypoint sh \
  avelren-privilege-gate:latest -c \
  'grep -c "\"schema_migrations\": {\"SELECT\"}" /workspace/app/tests/test_db_privileges.py'
```

Мусить бути **4**. Не 4 — образ несвіжий, перезбирай, вікно не відкривай.

### 2.5 Каталог evidence — **не передумова, а параметр**

Створювати його наперед **не треба**. `prepare_evidence_dir()`
(`deploy/postgres-ownership.lib.sh`) сам робить `mkdir -p`, ставить `chmod 700`
і звіряє власника з `id -u`. Фіксованого каталогу з таким іменем не існує —
шлях цілком визначає `AVELREN_EVIDENCE_DIR` при запуску.

```bash
EVID=/var/lib/avelren-adoption/evidence-3b2-$(git -C /opt/avelren rev-parse --short HEAD)-$(date -u +%Y%m%dT%H%M%SZ)
```

Вимог до нього рівно чотири, і всі перевіряє скрипт: **абсолютний**, **поза
`/opt/avelren`**, **не симлінк**, і власником стане той, хто запускає adoption.
Evidence усередині чекауту робить дерево брудним і відмовляє adoption — це вже
траплялось на попередній 3B.1.

> Попередження про «відсутній каталог evidence» — хибна тривога. Її дав мій
> власний аудит, що припустив статичний батьківський шлях, якого `adopt.sh`
> не споживає.

### 2.6 Шість DSN для гейта — **звір, що вони існують**

Раннер fail-close на кожному з: `AVELREN_ADMIN_TOOL_DSN`,
`AVELREN_COLLECTOR_DSN`, `AVELREN_NOTIFIER_DSN`, `AVELREN_WATCHDOG_DSN`,
`AVELREN_API_DSN`, `AVELREN_BACKUP_DSN`.

Чотири з них компоуз використовує сам, тож вони в `.env` майже напевно є.
`AVELREN_ADMIN_TOOL_DSN` і `AVELREN_BACKUP_DSN` компоуз **не** використовує —
перевір їх окремо, не припускай:

```bash
sudo grep -c '^AVELREN_ADMIN_TOOL_DSN=' /opt/avelren/.env
sudo grep -c '^AVELREN_BACKUP_DSN='     /opt/avelren/.env
# кожне має дати 1; значень НЕ друкуй
```

Якщо котрогось немає — **стоп**. Гейт впаде вже після коміту, і коректну
adoption відкотить.

### 2.6a `AVELREN_PSQL_BIN` — обовʼязково на бойовому хості

`_adoption_psql()` (`postgres-ownership.lib.sh:135`) викликає
`"${AVELREN_PSQL_BIN:-psql}"`. На хості `psql` **не встановлений** — він живе
лише в контейнері `db`. Без цієї змінної adoption відмовляється на
`admin connection failed` ще до будь-якої мутації.

Обгортку **не вигадувати**: у проєкті є еталон
(`deploy/postgres-adoption-bootstrap-topology-test.sh:132`), і в ньому — деталь,
яку саморобна версія втрачає: `_adoption_psql` кладе DSN у `PGDATABASE`, а
справжній `psql` **не розгортає URI зі змінної `PGDATABASE`**, тому її треба
передати позиційним conninfo всередині контейнера.

Покласти **поза чекаутом** (файл усередині `/opt/avelren` зробив би дерево
брудним і відмовив adoption):

```bash
cat >/var/lib/avelren-adoption/psql-in-db.sh <<'WRAP'
#!/usr/bin/env bash
cd /opt/avelren
exec docker compose exec -T -e PGDATABASE db \
    sh -c 'exec psql "$PGDATABASE" "$@"' _ "$@"
WRAP
chown root:root /var/lib/avelren-adoption/psql-in-db.sh
chmod 0700     /var/lib/avelren-adoption/psql-in-db.sh
```

Що зберігається: DSN іде **за іменем** через `-e PGDATABASE`, ніколи в argv;
`-T` пропускає stdin, яким adopt.sh подає плани; `exec` пробрасує код виходу.

> **Пастка запуску.** `docker compose exec -T` читає stdin. Якщо запускати
> `adopt.sh` через SSH-heredoc, перший же виклик psql зʼїсть решту скрипта.
> Запускай **файлом** (`bash deploy/postgres-adopt.sh …`), не потоком.

### 2.7 Операційний оверлей

```bash
ls -l /opt/avelren/docker-compose.override.yml
```

Рестарт після коміту явно іменує цей файл, бо на проді він постачає
`ECHERHA_*`, яких немає у відстежуваному compose і без яких `config.py`
fail-close. Якщо файлу немає — з'ясуй чому **до** вікна: інакше клієнти
піднімуться в другий режим відмови 14 серпня.

### 2.8 Базлайн для стоп-правил

```bash
sudo docker ps --format '{{.Names}}\t{{.CreatedAt}}\t{{.Status}}'
sudo docker inspect avelren-db-1 --format '{{.Id}} {{.State.StartedAt}}'
curl -fsS https://api.bordersignal.pp.ua/api/health
```

Запиши. Це те, з чим звірятимешся після.

---

## 3. Вибір моменту

Дрейф каталогу — головна причина «безпідставної» відмови. TimescaleDB створює
новий chunk на межі 7 днів; якщо він з'явиться між preflight-знімком і вікном,
adoption **відмовиться до першої мутації**:

```
ADOPTION REFUSED: catalog drifted between preflight and mutation window
```

Це запобіжник, що працює, а не аварія. Щоб не ловити його:

- запускай **одразу** після preflight, без пауз на каву;
- не в межах нічного бекапу (03:00–04:00 UTC);
- денний час — краще: збирач пише рівно, ніч нічим не краща.

---

## 4. Запуск

Значення DSN беруться з `.env` у середовище й **ніколи не потрапляють в argv**.

```bash
cd /opt/avelren
set -a; . ./.env; set +a

AVELREN_TARGET_DB=avelren \
AVELREN_ADMIN_DSN="<легасі avelren superuser DSN з .env>" \
AVELREN_EXPECTED_COMMIT="$COMMIT" \
AVELREN_RECOVERY_PREFLIGHT_FILE="$PREFLIGHT" \
AVELREN_EVIDENCE_DIR="$EVID" \
AVELREN_ADOPTION_SUCCESS_GATE_RUNNER="$RUNNER" \
AVELREN_PSQL_BIN=/var/lib/avelren-adoption/psql-in-db.sh \
AVELREN_STACK_DIR=/opt/avelren \
AVELREN_COMPOSE_PROJECT=avelren \
AVELREN_ADMIN_TOOL_DSN="$AVELREN_ADMIN_TOOL_DSN" \
AVELREN_COLLECTOR_DSN="$AVELREN_COLLECTOR_DSN" \
AVELREN_NOTIFIER_DSN="$AVELREN_NOTIFIER_DSN" \
AVELREN_WATCHDOG_DSN="$AVELREN_WATCHDOG_DSN" \
AVELREN_API_DSN="$AVELREN_API_DSN" \
AVELREN_BACKUP_DSN="$AVELREN_BACKUP_DSN" \
bash deploy/postgres-adopt.sh \
  --confirm-adoption AVELREN-POSTGRES-ADOPTION \
  --production-adopt \
  --production-token-file "$TOKEN" \
  2>&1 | tee "$EVID/run.log"
```

### 4.1 Замикання оточення — п'ятнадцять змінних, і чому саме стільки

Тричі поспіль вікно провалилось через неповний перелік. Тому нижче не «те, що
я згадав», а **механічне замикання**: усе, що читають `adopt.sh`,
`postgres-ownership.lib.sh` і `postgres-privilege-gate.sh` разом.

> **Корінь усіх трьох провалів — один, і він методологічний.** Контракт
> оточення виводили з `adopt.sh` — точки входу. А `adopt.sh` **породжує** інші
> процеси (обгортку psql, раннер гейта) і передає їм оточення успадкуванням, не
> експортом. Тому змінна може мати безпечний дефолт у точці входу і бути
> `:?`-fail-close у нащадку. Саме так і сталося тричі: `AVELREN_PSQL_BIN`
> (дефолт `psql`, якого на хості нема), `AVELREN_STACK_DIR` і
> `AVELREN_COMPOSE_PROJECT` (дефолти в `adopt.sh`, `:?` у раннері).
>
> **Правило на майбутнє:** контракт оточення рахується по **транзитивному
> замиканню процесів**, а не по точці входу. Для 3C це критично — там
> породжуються ще п'ять раннерів.
>
> **І друге джерело істини, про яке варто пам'ятати:** авторитетним виявився не
> лише код, а **фактичний launch-скрипт попередньої спроби** на хості
> (`run-3b2-<commit>.sh`). Він містив рівно ті три змінні. Читати код —
> правильно; читати код **і останній реальний запуск** — повніше.

**Пастка, яка коштувала коміту й відкату:** `adopt.sh` має дефолти для
`AVELREN_STACK_DIR` і `AVELREN_COMPOSE_PROJECT`, а раннер гейта fail-close на
обох через `:?`. Тобто adopt.sh спокійно доходить до коміту, а гейт
відмовляється, **не виконавши жодного асерту** → інверсний відкат коректної
adoption. Механізм тотожний інциденту 2026-08-14.

| # | змінна | чому потрібна |
|---|---|---|
| 1 | `AVELREN_TARGET_DB=avelren` | точна назва, звіряється |
| 2 | `AVELREN_ADMIN_DSN` | легасі суперюзер |
| 3 | `AVELREN_EXPECTED_COMMIT` | 40-hex, = HEAD |
| 4 | `AVELREN_RECOVERY_PREFLIGHT_FILE` | |
| 5 | `AVELREN_EVIDENCE_DIR` | свіжий шлях |
| 6 | `AVELREN_ADOPTION_SUCCESS_GATE_RUNNER` | |
| 7 | `AVELREN_PSQL_BIN` | на хості немає `psql` |
| 8 | **`AVELREN_STACK_DIR`** | **`:?` у раннері гейта** |
| 9 | **`AVELREN_COMPOSE_PROJECT`** | **`:?` у раннері гейта** |
| 10–15 | `AVELREN_{ADMIN_TOOL,COLLECTOR,NOTIFIER,WATCHDOG,API,BACKUP}_DSN` | шість `:?` у раннері гейта |

**Не встановлювати ЖОДНОЇ з цих:**

`AVELREN_COMPOSE_FILE` — окремо небезпечна, і не як «тест-змінна».
Іменування compose-файлу вимикає автопошук, і тоді рестарт після коміту
**втратить `docker-compose.override.yml`**, який на проді постачає `ECHERHA_*`.
Клієнти піднімуться у другий режим відмови 14 серпня. Лишити порожньою.

`AVELREN_TEST_DB`, `AVELREN_ADOPTION_FAILPOINT`,
`AVELREN_ADOPTION_POST_COMMIT_GATE`, `AVELREN_ADOPTION_COMMITTED_FAILPOINT`,
`AVELREN_ADOPTION_CORRUPT_INVERSE`, `AVELREN_PRODUCTION_TARGET_OVERRIDE`,
`AVELREN_PRODUCTION_DRIFT_INJECT`, `AVELREN_ALLOW_DIRTY_TEST`,
`AVELREN_CURRENT_DB_USER` — усе це тестові інʼєкції; більшість скрипт відкине
сам, але `AVELREN_CURRENT_DB_USER` підмінив би перевірку адмін-підключення
мовчки.

Ролі (`avelren`, `avelren_admin`, `avelren_migrator`) — `readonly` у
бібліотеці, не змінні. `AVELREN_DOCKER_BIN`, `AVELREN_GIT_BIN`,
`AVELREN_PRIVILEGE_GATE_{COMPOSE_FILE,SERVICE}` мають правильні дефолти.

### 4.2 Суха перевірка гейта — **обовʼязково перед запуском**

Це структурне виправлення того, що двічі провалилось: не давати post-commit
шляху містити крок, чиї передумови не перевірені під **тим самим** оточенням.

Візьми **той самий launch-файл**, заміни виклик `adopt.sh` на прямий виклик
раннера і прожени:

```bash
... той самий блок env ... \
bash "$RUNNER" privilege_contracts; echo "rc=$?"
```

Очікується падіння на `assert actual == expected` замороженого ACL — база ще не
адоптована. Це **успіх** перевірки: гейт дійшов до асертів, отже оточення повне.

Будь-яке інше падіння — `AVELREN_STACK_DIR is required`, `is required` на DSN,
помилка компоуза, `--noconftest` — означає, що оточення досі неповне.
**Вікно не відкривати.**

---

**Не встановлюй** `AVELREN_TEST_DB`, жодного failpoint, і не додавай
`--retire-legacy` — кожне з них скрипт відкидає окремою відмовою, і правильно.

---

## 5. Що відбувається всередині, по порядку

Щоб читати лог, а не гадати:

1. перевірка токена, комміта, чистого дерева, preflight, прав раннера;
2. **read-only** твердження, що всі 7 ролей існують (їх скрипт ніколи не створює);
3. знімок preflight-маніфесту володіння/ACL;
4. **вхід у вікно**: зупинка `caddy api collector notifier watchdog`; `db` лишається;
5. повторний знімок маніфесту вже без клієнтів → порівняння з п.3 (це і є drift-check);
6. побудова forward/inverse планів, доказ їх розбору й round-trip;
7. **КОМІТ** forward-плану;
8. гейт `privilege_contracts` — introspection-only pytest у одноразовому контейнері;
9. твердження, що легасі `avelren` лишився `SUPERUSER+LOGIN`;
10. публікація evidence `stage=committed`;
11. рестарт клієнтів на **незмінному** легасі DSN, з `--no-deps`;
12. `HARD STOP`.

Мутація починається аж на п.7. Усе до нього — відмова без наслідків.

---

## 6. Коди виходу — читай уважно, тут легко нашкодити

| код | означає | що робити |
|---|---|---|
| `0` | adoption закомічено, клієнти піднялись | перевірити health і зупинитись |
| **`3`** | **adoption закомічено і коректне, але клієнти не піднялись** | **НЕ відкочувати.** Підняти вручну: `docker compose up -d --no-deps caddy api collector notifier watchdog`, тоді health |
| інше | відмовлено або відкочено | читати лог; мутації або не було, або її знято інверсним планом |

**Про код 3 окремо.** Спокуса «щось пішло не так → відкотити» тут помилкова:
база вже в правильному стані, відкат зруйнував би коректну роботу. І в ручному
рестарті **обовʼязково `--no-deps`**: без нього Compose підтягне `migrate` як
залежність, той побачить 009, застосує й заштампує `010` поза послідовністю —
а інверсний план ACL відкотити зможе, штамп `010` — ні.

Ніколи не запускай голий `docker compose up -d` у цей момент.

---

## 7. Стоп-правила

Зупиняйся **до** запуску, якщо не сходиться будь-що з розділу 2.

Після запуску скрипт керує сам: він або доводить справу, або відмовляється, або
відкочує. Твоє завдання — **не втручатися** до появи коду виходу. Зокрема:

- не перезапускай сервіси руками, доки скрипт працює;
- не роби `docker compose up` у сусідньому терміналі;
- не редагуй `.env`.

Якщо процес обірвався (мережа, SSH) — **нічого не роби**, читай evidence:
`$EVID/stage` каже, в якому стані все зупинилось.

---

## 8. Відомі відмови й що вони означають

| повідомлення | означає |
|---|---|
| `exact commit mismatch` | `AVELREN_EXPECTED_COMMIT` ≠ HEAD |
| `worktree is dirty` | сторонній файл у чекауті; винести **поза** `/opt/avelren`, не видаляти evidence |
| `recovery preflight commit mismatch` | третій рядок preflight не той комміт |
| `production token file mode must be 0400 or 0600` | права токена |
| `post-commit gate runner mode must be 0500 or 0700` | права раннера |
| `production adoption requires a privilege-contract gate runner` | не задано `AVELREN_ADOPTION_SUCCESS_GATE_RUNNER` |
| `production target must be exactly avelren` | описка в `AVELREN_TARGET_DB` |
| `admin connection failed` | не задано `AVELREN_PSQL_BIN` (на хості немає `psql`), або обгортка не передає DSN позиційним conninfo. **Мутації не було** — це найперша перевірка |
| `catalog drifted between preflight and mutation window` | новий chunk між знімком і вікном; **нічого не мутовано**, повторити ближче до вікна |
| `production privilege-contract acceptance failed` | гейт впав **після** коміту → інверсний відкат. Дивитись, на чому саме: якщо на замороженому ACL — образ гейта несвіжий (розділ 2.4) |

---

## 9. Після успіху

Стан: володіння на семи ролях, ACL з `010`, `schema_migrations` = `009`,
легасі `avelren` `SUPERUSER+LOGIN`, клієнти на легасі DSN.

Перевірити й записати:

```bash
curl -fsS https://api.bordersignal.pp.ua/api/health
sudo docker ps --format '{{.Names}}\t{{.Status}}'
ls -l "$EVID"                      # stage, original.tsv, forward.sql, inverse.sql, …
git -C /opt/avelren status --porcelain
```

І потім — **зупинитись**. Це валідний стан спокою; у ньому можна стояти
місяцями. 3C продового режиму не має і сам не запуститься.

Чого **не** робити після 3B.2:

- голий `docker compose up -d` — підтягне `migrate` і заштампує `010` поза 3D;
- `deploy/backup.sh` замість розгорнутого `/usr/local/sbin/avelren-backup` — гранти для `avelren_backup` є вже зараз, але заміна скрипта це окрема зміна (#93), не побічний ефект вікна.
