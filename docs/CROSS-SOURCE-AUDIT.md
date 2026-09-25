# Cross-source контроль перенесення

Цей документ — контрольна рамка: новий репозиторій не вважається повною
заміною старих лише тому, що в ньому є схожі файли. Перед прийняттям зміни
звіряються чотири незалежні джерела:

1. старий `ikstv/AvelRen` — історія коду, Issues і PR;
2. приватний `ikstv/AvelRen-ops` — операційні контракти та recovery-докази;
3. фактичні артефакти — GitHub Release, AAB і встановлений на телефоні APK;
4. фактичний production runtime — Git checkout, Docker, міграції та SHA
   обраних встановлених файлів.

Це read-only аудит. Він не є дозволом змінювати телефон, сервер, міграції чи
старі репозиторії.

## Зріз 2026-09-25

| Джерело | Ідентичність | Висновок |
| --- | --- | --- |
| `AvelRen-ORIGINAL/main` | `65b29a986d79fcb27e1d2edfdab0749e0dc520f7` | Поточне джерело для нових змін; воно не дорівнює автоматично ні Play-версії, ні production. |
| Старий `AvelRen/main` | `4a8e010aeb02d2d77fef3fc1297e67f4f5e5ab27` | Контрольне джерело для legacy code/PR/Issues; не видаляти до завершення реєстрів. |
| `AvelRen-ops/main` | `5be9da8b433813a664b4d4e21a0a92bae91c56a0` | Контрольне джерело старих runbook та recovery-доказів; його GitHub Issues на момент зрізу відсутні. |
| GitHub Release `v0.1.1` | AAB `AvelRen-0.1.1-57e6146-release.aab`, commit `57e614645be43bbd5bddced89d5f309c20be58b0`, SHA-256 `8a4c6b79d9a81bccd422fee4389a6500b7f5c8e3baec684b254ae64558b95ea7` | Офіційний bundle 0.1.1/4; він старший за поточний `main`. |
| Телефон | Play-встановлення `ua.avelren.app`, version `0.1.1` / code `4`, base APK SHA-256 `47c67fa0f814f3c827de7bc33f923ee2014ecbe5fb23d29ae47702fc8162c86f` | Base APK підписаний Google Play App Signing. Його SHA не порівнюється безпосередньо з AAB SHA: Play генерує split APK. Потрібен зв’язок Play track → AAB → GitHub Release, якщо треба довести точний commit. |
| Production checkout | `/opt/avelren`, HEAD `81e5b047f8f18c42ca46a59f86495f71d0681af0`, дерево dirty | Не є чистою копією жодної гілки. Відрізняються `watchdog.py`, privacy policy і telemetry snapshot, присутні резервні override-файли. Нічого не очищати без окремого рішення. |
| Production DB | read-only перелік міграцій `001`–`013` | Старі документи, де вказано лише `001`–`009`, є історичним зрізом, а не поточним фактом. |

## Виявлені розбіжності

| Область | Факт | Безпечне трактування |
| --- | --- | --- |
| Server migrations | Поточна DB має 010–013, хоча старий аудит 23.09 фіксував 001–009. | Не застосовувати й не відкотити міграції. Перед будь-яким restore/deploy повторювати read-only schema/role preflight і оновлювати evidence. |
| Server runtime | API, notifier, watchdog і collector працюють з різними image references; checkout dirty. | Не вважати сервер відтворюваним із поточного `main`; спершу класифікувати кожну різницю. |
| Встановлені скрипти | `backup.sh` і `telemetry-snapshot.sh` на сервері мають SHA, що збігаються з current ORIGINAL source. Host maintenance/reboot scripts мають інші SHA від current ORIGINAL source. | Не перезаписувати scripts. Окремо порівняти semantic diff і зафіксувати, який варіант приймається перед майбутнім deployment. |
| Android | Телефон має Play-артефакт 0.1.1/4, а current ORIGINAL main уже містить пізніші зміни. | Не стверджувати, що нова функція є на телефоні, доки не зібрано/опубліковано/перевірено конкретний артефакт. |
| Legacy Issues | Старий `AvelRen` має 9 відкритих Issues. | Кожна має статус у [реєстрі legacy Issues](LEGACY-ISSUE-REGISTER.md); переносити не лише PR diff, а й пов’язану проблему. |

## Детальна класифікація runtime (read-only, 2026-09-25)

Це уточнення зрізу. Воно не є планом змін на production і не дозволяє
копіювати файли з host у Git без окремої перевірки.

| Артефакт | Зіставлення | Рішення |
| --- | --- | --- |
| Міграції production | Журнал DB містить `001`–`013`, але checkout `/opt/avelren/db/migrations` містить лише `001`–`010`. SHA journal для `011`–`013` точно збігаються з `AvelRen-ORIGINAL/db/migrations/011_admin_access.sql`, `012_device_retention.sql` і `013_admin_installation_lock.sql`. | **Provenance підтверджено; checkout застарів.** Не застосовувати, не відкочувати й не редагувати міграції. Server checkout не можна використовувати як deployment/restore source, доки його стан не буде окремо узгоджено й пройдений schema/role preflight. |
| Collector | SHA source у контейнері збігається зі старим кодом і current ORIGINAL. | **Перенесено.** Не потребує копіювання з host. |
| Notifier | SHA source у контейнері збігається зі старим кодом і current ORIGINAL. | **Перенесено.** Не потребує копіювання з host. |
| API | Серверний source SHA походить зі старого історичного коміту external health gate (#174/#175). Семантика `alert_channel` та `undelivered_alerts` уже є в current ORIGINAL, хоча runtime SHA не дорівнює SHA current source. | **Функціонально перенесено; runtime неідентичний.** Перед deployment потрібна звірка повного diff, а не заміна образу за SHA. |
| Watchdog | Server source SHA не знайдено в доступній Git-історії; checkout також має незакомічену зміну `watchdog.py`. | **Невідомий host drift.** Не переносити автоматично; спочатку виділити й протестувати поведінковий diff. |
| Privacy policy і telemetry snapshot | Встановлені на server SHA збігаються з current ORIGINAL. Вони відображають політику автоматичного очищення після 90 днів без email. | **Перенесено.** Dirty checkout не означає, що ці файли слід відкотити. |
| Host maintenance/reboot scripts | SHA на host відрізняються від current ORIGINAL source. | **Потребує semantic diff.** Не перезаписувати host scripts до окремого рішення й явного GO. |
| Backup/Compose резервні файли на host | Виявлені untracked backup/override файли можуть містити секрети. | **Оpaque.** Не читати, не комітити й не копіювати без окремої процедури поводження з секретами. |

Найменший безпечний наступний крок після цього документа — зафіксувати окремий
deployment preflight, який відхиляє застарілий server checkout і звіряє journal
із source migrations в ізольованому середовищі. Це підсилює відтворюваність,
не торкаючись production.

## Обов'язковий порядок звірки

### Перед перенесенням функції

- знайти пов’язані старі PR, Issues і ops-документи;
- записати для кожного артефакту: перенесено, замінено, ще потрібно перенести
  або свідомо відкинуто з причиною;
- не змішувати historic production drift із автоматичною зміною нового коду.

### Перед прийняттям Android-зміни

- збирати APK/AAB лише з чистого `main`;
- зберегти commit, versionName/versionCode, artifact SHA-256 і дату в
  `dist/BUILD.txt`;
- для встановленого телефона зчитати package metadata та витягнути base APK
  для SHA-256;
- для Play-встановлення звірити track/version із AAB і GitHub Release, а не
  порівнювати SHA base APK із SHA bundle.

### Перед будь-якою server-дією

- повторити read-only: server HEAD/status, image references, migration history,
  runtime script SHA і service health;
- зіставити кожну planned зміну з точним source commit та перевіреним тестом;
- вимагати окремого explicit GO на конкретні host-команди;
- після дії повторити той самий fingerprint і записати різницю.

## Межа рішення

Розбіжність не означає автоматичний fix або deployment. Вона стає або
підтвердженим перенесенням, або окремою задачею, або свідомо відхиленим
історичним матеріалом. Старі `AvelRen` і `AvelRen-ops` залишаються
контрольними джерелами, доки цей реєстр, legacy PR/Issue register, Android
release evidence та backup/recovery перевірки не матимуть явного рішення.
