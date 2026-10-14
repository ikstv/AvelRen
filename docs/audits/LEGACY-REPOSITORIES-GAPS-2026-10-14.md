# Залишки двох старих репозиторіїв — 14.10.2026

Read-only звірка GitHub і source ORIGINAL виконана 14.10.2026 приблизно
11:15–11:25 за Києвом. Issues/PR не закривали, workflow не запускали,
налаштування й сервер не змінювали. Це інвентаризація залишків, не дозвіл
видалити старі репозиторії й не новий аудит робочого сервера.

## Джерела та межі

| Репозиторій | Main | Відкриті issues / PR | Гілки / теги |
| --- | --- | --- | --- |
| [AvelRen](https://github.com/ikstv/AvelRen) | `4a8e010aeb02d2d77fef3fc1297e67f4f5e5ab27` | 8 / 11 | 19 / 2 |
| [AvelRen-ops](https://github.com/ikstv/AvelRen-ops) | `5be9da8b433813a664b4d4e21a0a92bae91c56a0` | 0 / 1 | 2 / 0 |

Обидва main збігаються з раніше зафіксованими джерелами. Новіші дати push
не доводять зміну main. Source порівнювався з head PR #128 `8e29413`;
наприкінці звірки він увійшов у ORIGINAL main `ab74e078`.
Повну побайтову еквівалентність усіх історичних гілок і бінарних ресурсів
не перевіряли. Відкритий старий issue не означає відсутність його коду в ORIGINAL.

## Issues: що перенесено та що залишається

| Issue AvelRen | Висновок |
| --- | --- |
| [#196 maintenance](https://github.com/ikstv/AvelRen/issues/196) | Плашка й API/notifier deployment прийняті за [аудитом 12.10](API-NOTIFIER-DEPLOYMENT-2026-10-12.md). Власник замінив розширений план коротким вікном до 15 хвилин; старий план не відновлюємо автоматично. |
| [#111 missing/zero](https://github.com/ikstv/AvelRen/issues/111) | Код і migrations015/016 перенесені; [ORIGINAL #70](https://github.com/ikstv/AvelRen-ORIGINAL/issues/70) зберігає телефонні сценарії missing/null/справжній 0/ETA. |
| [#110 два ПК](https://github.com/ikstv/AvelRen/issues/110) | Застарілу операційну нотатку замінюють CONTRIBUTING і SECRETS-RECOVERY. Роботу домашнього ПК цим аудитом не підтверджено. |
| [#26 hardening](https://github.com/ikstv/AvelRen/issues/26) | Загальний реєстр дочірніх робіт, не окремий відсутній серверний компонент. |
| [#25 privacy/runbooks](https://github.com/ikstv/AvelRen/issues/25) | Policy, retention і recovery документи є. У `apps/android/app/build.gradle.kts` залишилися два посилання на відсутній `docs/release-signing.md`; signing інструкції є в SECRETS-RECOVERY. Privacy/deletion/access-log приймання загалом не закрите. |
| [#23 supply chain](https://github.com/ikstv/AvelRen/issues/23) | Pins, locks і SBOM є. Відсутні Dependabot config, CodeQL workflow, Gradle verification metadata та регулярні dependency/container audit jobs. Це окреме посилення захисту. |
| [#19 FCM/retention](https://github.com/ikstv/AvelRen/issues/19) | Typed409 ownership і bounded Android recovery перенесені; retention є. Явного delete-installation API/Android cleanup немає; DELETE subscription/eta-target не замінює його. Новий контракт не реалізує автоматично всі старі challenge/proof-of-possession побажання. Потрібне окреме рішення обсягу та телефонне приймання. |
| [#15 права БД](https://github.com/ikstv/AvelRen/issues/15) | Executor, contracts і runbooks перенесені. Production ownership/ACL/roles/DSN лишаються окремим етапом після приймання спільного backup/restore. Старі schema009 команди не застосовувати як є. |

## Відкриті PR: повторно переносити не все

| Старі PR | Висновок |
| --- | --- |
| [AvelRen #199](https://github.com/ikstv/AvelRen/pull/199) | Новий Actions update, head `702cd3c0d6aa69d6a253ff82e8f5da53b6fae799`; #140 закритий 02.10. SBOM pin уже є; setup-gradle6.4 update ще не перенесений; CodeQL належить до #23. |
| [#190](https://github.com/ikstv/AvelRen/pull/190), [#183](https://github.com/ikstv/AvelRen/pull/183) | Retention замінено migration012/worker/tests ORIGINAL. |
| [#188](https://github.com/ikstv/AvelRen/pull/188) | Daily status/telemetry замінено перенесеним watchdog і його production provenance. |
| [#185](https://github.com/ikstv/AvelRen/pull/185) | Forecast замінено актуальним `forecast.evaluate` і тестами; телефонне приймання окреме. |
| [#184](https://github.com/ikstv/AvelRen/pull/184) | Premium свідомо відкинуто в реєстрі як нову продуктову обіцянку; міграція не вмикає його. |
| [#173](https://github.com/ikstv/AvelRen/pull/173) | Застарілий generated STATE snapshot відкинуто. |
| [#143](https://github.com/ikstv/AvelRen/pull/143), [#138](https://github.com/ikstv/AvelRen/pull/138) | Старі image/Python updates замінено пізнішими pinned versions ORIGINAL. |
| [#137](https://github.com/ikstv/AvelRen/pull/137) | Плашка перенесена; кінцевий APK потребує своїх сценаріїв. |
| [#123](https://github.com/ikstv/AvelRen/pull/123) | Dated signals замінено принципом датованих доказів у CONTRIBUTING/audits. |
| [AvelRen-ops #1](https://github.com/ikstv/AvelRen-ops/pull/1) | Head `a952262420a3ba629db4f8c27befdd2e1ee6b2cb`: лише історичний image-parity аудит 28.09. Зберегти історію; старі image assumptions не є поточними командами. |

## Функції, ресурси й операційні залежності

| Залишок | Перевірений стан / наступна дія |
| --- | --- |
| Release notification, R08 | У старому `release_notice.py` є лише payload helper, немає готового sender/Play availability gate. Helper відсутній у ORIGINAL; Android handler є. Визначити обсяг перенесення окремо; не оголошувати всю функцію готовою. |
| Read-only restore smoke | ORIGINAL має internal health verification та isolated real API/auth/DB smoke. Старий helper перевіряв також GET checkpoints; повна parity не заявляється. |
| Зовнішній monitor | Старий workflow лишається active; новий у ORIGINAL ручний. Потрібні live приймання та рішення розкладу до вимкнення старого. |
| П'ять Play PNG | `play-assets/final/{feature-1024x500,icon-512,screen-01,screen-02,screen-03}.png` з ops відсутні серед tracked файлів ORIGINAL. Зберегти з provenance або явно відкинути після перегляду; серверну роботу вони не блокують. |
| Backup/restore, INTEGRATION, adoption, telemetry, privacy, Play copy | Основні counterparts перенесені/адаптовані в `ops/`, `docs/`, root INTEGRATION. Це не підтверджує поточний paired restore, live DSN cutover або Play publication. |
| Історія | До видалення потрібні відновлюваний Git archive, issue/PR export та рішення щодо старих гілок/ресурсів. Самі посилання на майбутній видалений repo не є архівом. |

Закриті operational issues зберігають історію інцидентів, але не створюють
нові відкриті code gaps автоматично. Втрата device secret за погодженим
контрактом створює нову installation без доступу до старих підписок;
збіг FCM token не є дозволом їх переносити.

Поточні пріоритети: реальна off-host пара та isolated restore, перехід БД,
заміна старого монітора, кінцевий APK/телефон, рішення щодо перелічених source
і asset gaps, збереження історії. [Поточний реєстр](../MIGRATION-REMAINING.md)
відділяє ці роботи від уже прийнятих source/CI/deployment етапів.
