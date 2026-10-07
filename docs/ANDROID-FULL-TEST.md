# Повнофункціональна 1.0.3 Test

Власник погодив 07.10.2026 окремий Test поруч з офіційним застосунком,
усі сьогоднішні зміни, реальний API, FCM/голос, без локальних фікстур.
Погодив інтеграцію PR #100 після зеленого CI. Це не дозвіл GitHub/Play publication.

`-PavelrenFullTest=true` — debug-only, пакет `ua.avelren.app.test`,
версія `1.0.3-test`, назва `AvelRen — 1.0.3 Test`. Використовує штатні
`AvelRenApp`, `MainActivity`, API, реєстрацію, підписки, ACK, FCM і голос.
Manifest змінює тільки назву. Інші test modes взаємно виключні;
release task у цьому режимі заборонений. Тестові QA/Preview activities
і експортований probe receiver не включаються.

Окремий Firebase client `ua.avelren.app.test` з назвою
`AvelRen 1.0.3 full Test 2026-10-07` створений через погоджений серверний
доступ. Before/after звірка підтвердила незмінність робочого клієнта.
Не змінено IAM, service-account keys або робочий Android client.
Конфігурація збережена поза Git, у захищеній директорії користувача.
Жоден серверний ключ не включається в Android config чи APK.

Вкажіть справжній properties-файл через `-PavelrenFullTestConfig=<absolute path>`:
`packageName`, `googleAppId`, `senderId`, `apiKey`, `projectId`.
Package має точно відповідати `ua.avelren.app.test`; конфігурацію
офіційного клієнта не підмінювати. Default `full-test.properties` gitignored.
`app/src/fullTest/fixture.properties` — тільки для compile/CI;
APK із нею не встановлювати й не запускати.

На телефоні Test — окрема інсталяція з власним device ID, підписками,
ACK і налаштуваннями; адмін-доступ не копіюється і не обходиться.
Обидва застосунки можуть отримувати сповіщення за власними підписками;
оператор має відрізняти їх, щоб не трактувати це як дубль одного застосунку.
У «Сервер» три live смужки CPU/RAM/Disk; Traffic UI відкладено, хоча nullable
traffic поле API збережене для сумісності. Витрати не реалізуються.

Перед телефоном: чистий актуальний main, повні checks, справжній config,
APK SHA/commit/date у dist/BUILD.txt і readback installed base.apk.
Перед встановленням — погоджений звуковий сигнал та повідомлення власнику.
Голос/підписки/offline/admin, обидві теми і великий шрифт приймаються
реальними сценаріями; compile/JVM/manifest checks їх не замінюють.
Після тестування — погоджений опис GitHub/app/Play і окреме release APK/AAB.
