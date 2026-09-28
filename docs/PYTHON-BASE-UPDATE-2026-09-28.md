# Кандидат оновлення Python — 28.09.2026

Статус: функціональні перевірки й первинний розбір CVE завершено; залишковий
ризик SUID/capabilities ще потребує рішення й перевіреного посилення захисту.
Не зливати й не розгортати до закриття цього gate. Legacy PR #138 поки
залишається відкритим залишком перенесення.

## Зміна

База роботи: main `53d90f1b325f76e3ab46ac93abb52aaa03cb7bd0`.
У `services/backend/Dockerfile` та `ops/Dockerfile.database-test`
узгоджено замінено digest `python:3.14-slim`:

- Було: `sha256:ce40764625a4ff50df3548277632e7f96c4e77fe75fa848aae9885476e7df5a4`.
- Кандидат: `sha256:51dafde81dbdb6ebde285137a295cf18a47ca95234fe388a343719cb97305b3d`.

Registry перевірено через `docker buildx imagetools inspect`: Python
`3.14.7-slim-trixie`, образ від 19.09.2026. Це новіший кандидат, ніж
`cad9a2c…` зі старого PR; старий diff не копіювався механічно.
`requirements.lock`, прикладний код і міграції не змінювались.

## Локальні перевірки

- Обидва Dockerfile успішно зібрано.
- Backend unit: **200 passed**, дві deprecation warnings у test client.
- Database: **22 passed**, перевірка `pg_dump` пройшла.
- API: **56 passed**, ті самі дві deprecation warnings.
- Watchdog: suite виконано успішно як частину послідовного matrix-run.
- `ops/restore-integration-test.sh`: успішний ізольований restore_test,
  перевірено 14 міграцій, least-privilege schema/API smoke та cleanup
  після навмисної помилки restore. Увесь matrix-run завершився кодом 0.
- Runtime: Python **3.14.7**, UID **10001**, імпорти API/collector/notifier/
  watchdog успішні; `pip check`: `No broken requirements found`.

Тести використовували синтетичні дані й окремі Compose-проєкти, не production
та не первинне джерело. Android/APK/телефон у цьому кроці не перевірялися.

## Перевірка вразливостей і межі висновку

Trivy **0.74.0**, образ сканера
`sha256:62b1e65e8869bc4b4c6aa4fa2b21595256c7c2f6018a9d9ad61caf87187c1969`.
База CVE оновлена **28.09.2026 07:15:22 UTC**.
Базу завантажено окремим контейнером без доступу до коду чи образу застосунку;
скан архіву виконано з `--network none --skip-db-update --offline-scan
--scanners vuln`. Приватний образ/SBOM не передавалися зовнішньому сервісу.

Результат — записи «пакет × вразливість», не кількість унікальних CVE:

| Складова | Critical | High | Medium | Low | Unknown |
| --- | ---: | ---: | ---: | ---: | ---: |
| Debian 13.7 | 0 | 44 | 53 | 57 | 2 |
| Python / SBOM | 0 | 2 | 1 | 0 | 0 |

Debian High у цій базі не мають `FixedVersion`; це не доказ їхньої
безпечності або доступності експлуатації через API. Потрібна оцінка
досяжності та порівняння з попереднім образом на тій самій CVE-базі.

Python-знахідки:

- `GHSA-6v7p-g79w-8964`: msgpack 1.1.2, High, виправлення 1.2.1.
  Прямий `import msgpack` відсутній, але в pip 26.2.1 підтверджено
  `pip._vendor.msgpack` версії 1.1.2. Оновлення окремого msgpack не
  замінює vendored-копію pip. Прикладна досяжність ще не доведена.
- `CVE-2025-47273`: setuptools 70.3.0, High, виправлення 78.1.1.
- `CVE-2026-59890`: setuptools 70.3.0, Medium, виправлення 83.0.0.
  Обидві знахідки setuptools походять із SBOM; прямий модуль у runtime
  не знайдено. Походження запису потребує уточнення, це не підтверджений
  runtime-пакет і не автоматично хибна знахідка.

Trivy попередив про сторонній SBOM і можливу неточність визначення.
Успішний вихід сканера означає виконаний скан, а не відсутність CVE.
Локальний повний звіт: `dist/python-refresh-audit/runtime-cves.json`,
SHA-256 `2714435c70756fc1fe380eb4216b01c7f161fd0d2ae62270604784bd412839b5`.
Архів образу й повний звіт залишені в ігнорованому `dist/`, не у Git.

## Наступний малий крок

Завершити CVE review: порівняти старий і новий runtime, уточнити setuptools
SBOM, оцінити vendored msgpack та системні знахідки. Визначити виправлення
або документоване обґрунтування непридатності до runtime; повторити скан
і відповідні тести. Лише тоді завершувати #138 та переходити до Caddy.
Production deployment залишається окремою погодженою операцією.

## Порівняння та уточнення 28.09.2026

Старий runtime повторно зібрано з digest `ce407646…`, тим самим source
і `requirements.lock`. Інструкції baseline Dockerfile відповідають runtime
Dockerfile, крім базового digest та коментарів. Це локальна реконструкція,
не образ активного production-контейнера. PEP 517 build dependency лишається
непінованою в обох варіантах — абсолютної відтворюваності build не заявляємо.
Обидва runtime повертають **Python 3.14.7**: змінюється базовий образ і
системні пакети (Debian 13.6 → 13.7), а не версія інтерпретатора.

Baseline зібрано командою `docker build -t avelren-python-baseline:local
-f dist/python-refresh-audit/Dockerfile.baseline services/backend`,
експортовано `docker save -o dist/python-refresh-audit/baseline.tar
avelren-python-baseline:local`. Скан — тими самими Trivy 0.74.0 і CVE DB
07:15:22 UTC, з `--network none`, `--skip-db-update`, `--offline-scan`,
`--scanners vuln`, `--input /audit/baseline.tar --format json`.

| Увесь runtime, пакет × CVE | Старий | Кандидат |
| --- | ---: | ---: |
| Critical | 3 | 0 |
| High | 86 | 46 |
| Medium | 104 | 54 |
| Low | 85 | 57 |
| Unknown | 2 | 2 |

Порівняння ключів `PkgName|VulnerabilityID|Severity`: **121 прибраний запис,
0 нових**. Це зменшення scanner findings, не гарантія відсутності ризику.
Baseline-звіт: `dist/python-refresh-audit/baseline-cves.json`, SHA-256
`d41182265cf5304ca5d30e0c11da482ee10ceeb4cb7d0e49b910acd31b2c0053`.

### Походження Python-знахідок

Усі три Python-знахідки однакові в baseline і кандидата. Їх джерело —
`/usr/local/lib/python3.14/site-packages/pip/_vendor/bom.cdx.json`.

- Setuptools 70.3.0 у SBOM представляє vendored `pkg_resources`.
  У site-packages немає `setuptools/package_index.py` і `filelist.py`,
  як і імпортованого top-level setuptools. Для перевіреного runtime
  відсутні конкретні компоненти, до яких віднесено дві CVE; це не
  твердження про безпеку непінованого build-time setuptools.
  [Advisory PackageIndex](https://github.com/pypa/setuptools/security/advisories/GHSA-5rjg-fvgr-3xxf).
- Vendored msgpack 1.1.2 реально є, але `Unpacker.__module__` дорівнює
  `pip._vendor.msgpack.fallback`: C-extension у цьому каталозі немає.
  CacheControl використовує `msgpack.loads`, а реалізація `unpackb`
  створює новий Unpacker на кожен виклик. Передумову повторного
  використання Unpacker після помилки тут не виявлено. Backend не
  імпортує pip/msgpack і не запускає subprocess.
  [Передумови advisory](https://github.com/msgpack/msgpack-python/security/advisories/GHSA-6v7p-g79w-8964).
  Сторінка автора ще називає 1.2.1 майбутнім виправленням, тоді як
  CVE DB вказує FixedVersion 1.2.1; версію для оновлення окремо не перевіряли.

### Системні High: попередня оцінка досяжності

44 записи відповідають восьми унікальним CVE. Усі лишилися від baseline;
у цій CVE DB немає готових FixedVersion.

| CVE / компонент | Перевірені межі |
| --- | --- |
| CVE-2026-16742 / systemd-homed | У кандидата немає `/usr/lib/systemd/systemd-homed`; наявність бібліотек systemd сама по собі не доводить наявності цього сервісу. |
| CVE-2026-9538 / Perl Archive::Tar | У `/usr/share/perl` не знайдено Tar.pm; backend не запускає Perl. Це вузька перевірка, не інвентаризація всіх шляхів Perl. |
| CVE-2025-69720 / infocmp | Backend не запускає зовнішні команди; окрема експлуатація CLI не оцінювалась. |
| CVE-2026-54369 / libacl | Потрібна перевірка привілейованих ACL-викликів; UID10001 сам по собі не виключає ризику. |
| CVE-2026-76642, CVE-2026-78408/78409/78410 / util-linux | У кандидата fstab містить лише UNCONFIGURED-коментар. Потрібна окрема оцінка mount/nsenter, SUID/capabilities і реального deployment; production не перевірявся. |

Не додавали ignore/VEX-виключень і не приховували raw findings.
Висновок: кандидат покращує scanner baseline, але остаточне приймання
залишкових системних ризиків ще відкрите.

### Новий блокер CI

Для head `bcbccda` пройшли api/core/repository/watchdog. Database CI
[36406608133](https://github.com/ikstv/AvelRen-ORIGINAL/actions/runs/36406608133)
зупинився на `compose-production-contract-test.sh`:
`migrate is not reachable even with its profile`.
Прямий локальний `docker compose --profile migrate -f docker-compose.yml
config --services` повертає migrate. Причину відмінності CI ще не
доведено; не приписуємо її Python чи самій production-конфігурації.
Тест приховує stderr і використовує `grep -q` під pipefail, тому спочатку
потрібне відтворення з окремою фіксацією виходів Compose та pipeline.
**PR лишається чернеткою.** Наступний крок — усунути підтверджену причину
CI та завершити оцінку системних ризиків перед рішенням про merge.

### Виправлення Compose guard (28.09.2026)

На Linux із Compose v5.5.1 відтворено pipeline statuses `141 0` для
`compose config --services | grep -qx migrate`, тоді як читання всього
виводу в файл завершувалося кодом 0 і містило migrate. Причина — раннє
закриття pipe командою grep, SIGPIPE у Compose та pipefail у сценарії.
Це дефект перевірки, не доказ несправності production-конфігурації.

Guard тепер повністю зчитує список сервісів, перевіряє exit status Compose
і лише після цього шукає migrate. Помилки discovery мають окремі причини;
приватний stderr не публікується. Production Compose не змінено.

Додано `python3 ops/compose-profile-regression-test.py` у database CI:
реальний Compose config з контрольованим потоком stdout, без запуску служб.
Чотири сценарії: правильна конфігурація з потоковим виводом; помилка Compose;
помилкова присутність migrate у default services; недоступний migrate profile.
До виправлення: три failures із чотирьох. Після: **4/4 OK** у Linux
контейнері з `--network none`, без Docker socket. GitHub CI має підтвердити
новий head; CVE-приймання лишається окремим незавершеним етапом.

## Підсумок системного CVE review (28.09.2026)

Для `f8b78bfd0e5d062ccc23acdbafcea14e1d3b5c01` пройшли всі п'ять GitHub
checks: api, core, database, repository, watchdog. Помилку Compose guard
закрито; database run `36408968768` також підтвердив restore та регресії.

Перевірено локальний runtime `avelren-python-refresh:local`, без мережі,
Docker socket, production mounts і запуску collector. Це не перевірка
активного сервера чи його локальних Compose overrides.

### Фактичні права й компоненти

- UID/GID 10001; CapInh/CapPrm/CapEff/CapAmb — нуль.
- CapBnd `00000000a80425fb`: CAP_SYS_ADMIN відсутня.
- Seccomp 2; **NoNewPrivs 0** — заборона підвищення привілеїв не ввімкнена.
- `/usr/bin/mount` і `/usr/bin/umount` мають SUID root. У runtime також
  залишилися SUID/SGID утиліти керування обліковими записами.
- `/etc/fstab` root-owned, mode 0644, не доступний UID10001 для запису;
  містить лише UNCONFIGURED-коментар. nsenter не має SUID.
- `systemd-homed` відсутній. `perl -MArchive::Tar` завершується відсутністю
  модуля в усіх налаштованих `@INC`, а не лише в одному перевіреному каталозі.
- infocmp та libacl залишаються в образі. Backend не містить викликів
  subprocess/os.system, mount/nsenter, infocmp чи ACL-функцій.
- Source Compose не додає privileged, cap_add, host PID namespace,
  root user або writable fstab; для Python-служб немає й явних
  `cap_drop: [ALL]` / `no-new-privileges`. Runtime defaults не замінюють
  перевірку конкретного deployment на сервері.

### Рішення по групах знахідок

| Знахідка | Висновок для перевіреного кандидата |
| --- | --- |
| [systemd-homed CVE-2026-16742](https://security-tracker.debian.org/tracker/CVE-2026-16742) | Вразлива служба відсутня; встановлені бібліотеки systemd не означають наявності homed-сценарію. |
| [Archive::Tar CVE-2026-9538](https://security-tracker.debian.org/tracker/CVE-2026-9538) | Вразливий Perl-модуль не встановлено в runtime `@INC`; шлях обробки tar цим модулем не доступний. |
| [infocmp CVE-2025-69720](https://security-tracker.debian.org/tracker/CVE-2025-69720) | CLI присутній, прикладного шляху запуску не знайдено. Не позначати весь ncurses як виправлений. |
| [libacl CVE-2026-54369](https://security-tracker.debian.org/tracker/CVE-2026-54369) | Привілейований ACL-виклик із керованим шляхом у backend не знайдено; бібліотека лишається вразливою за Debian tracker. Нуль CapEff не є універсальним захистом від SUID-сценаріїв. |
| [mount CVE-2026-76642](https://security-tracker.debian.org/tracker/CVE-2026-76642), [CVE-2026-78409](https://security-tracker.debian.org/tracker/CVE-2026-78409), [CVE-2026-78410](https://security-tracker.debian.org/tracker/CVE-2026-78410) | Немає fstab-дозволів, CAP_SYS_ADMIN чи прикладного запуску mount. Передумови відомих сценаріїв у цьому запуску не виявлено, але SUID mount та NoNewPrivs=0 лишають зайву можливість підвищення привілеїв. |
| [nsenter CVE-2026-78408](https://security-tracker.debian.org/tracker/CVE-2026-78408) | Потрібна привілейована операція nsenter; backend її не виконує, nsenter не SUID. Не використовувати root nsenter проти недовіреного target під час експлуатації. |

Debian tracker підтверджує невиправлені trixie-пакети acl/util-linux;
виправлення в unstable не є дозволом змішувати Debian releases у runtime.
Не запускали експлойти, не знімали обмеження контейнера та не додавали
scanner exclusions. Нижчі severity з raw scan також не оголошуються
виправленими: цей розбір пріоритезує залишкові High.

### Конкретний наступний крок

Окремо підготувати й перевірити `no-new-privileges:true` та `cap_drop: [ALL]`
для п'яти Python-служб (migrate, collector, notifier, watchdog, api),
не поширюючи це механічно на PostgreSQL чи Caddy. Перевірити Compose
контракти, runtime права, DB/API/watchdog і restore на ізольованих даних.
Це запропоноване посилення, **ще не реалізоване**; воно зменшує можливість
підвищення привілеїв, але не видаляє CVE з пакетів і не усуває DoS-класи.
Після перевірок — окремо оцінити готовність merge; production deployment
потребує власного GO та звірки фактичних overrides. PR #56 лишається draft.
