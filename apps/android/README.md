# Android-застосунок

База: `ikstv/AvelRen`, коміт `4a8e010aeb02d2d77fef3fc1297e67f4f5e5ab27`,
версія 0.1.1 (versionCode 4). Не застаріла робоча папка й не незлитий PR #137.
Походження 64 файлів: [маніфест](../../docs/ANDROID-PROVENANCE.json).
Зміни плашки: [контракт стану](../../docs/SERVER-STATUS.md).

## Перевірка

Офлайн `-PavelrenUiPreview=true` відкриває спільну навігацію через
`PreviewActivity` з локальним `PreviewAppClient`. Звичайний запуск показує
спільний повнорозмірний інтерфейс із темою ROAD SIGN без службової панелі.
Окремий службовий діалог (лише launch extra `preview_controls=true`) перемикає
порожній список, прогноз, факт, помилку зв'язку, п'ять КПП й недоступний
прогноз. Назва «AvelRen — тест», версія `1.0.3-test`, package `.preview`.
Дані синтетичні; production API/FCM/реєстрація не використовуються.
ACK видаляє локальну подію без server worker. Зміна сценарію оновлює дані
без скидання навігації. `src/previewTest` включається тільки в preview JVM suite.
Телефонний smoke-тест стандартного запуску: `tools/Test-PreviewDefaultScreen.ps1`
із параметрами `-Adb <шлях>` і `-Serial <пристрій>` з кореня репозиторію.
Службове меню відкривається через `adb shell am start -S -n
ua.avelren.app.preview/ua.avelren.app.PreviewActivity --ez preview_controls true`.

Потрібні JDK 17 та Android SDK 36. З цієї папки:

```sh
bash gradlew -PavelrenUiPreview=true :app:testDebugUnitTest :app:compileDebugKotlin --no-daemon --max-workers=2
```

На Windows замість `bash gradlew` використати `.\gradlew.bat`.
Це компіляція та JVM-тести, не встановлення APK. Preview вимикає Google
Services plugin; Firebase-ключі, підпис і реальні мережеві виклики для тестів
не потрібні. Реальний FCM і Play Update цим прогоном не перевіряються.
Окремий workflow Android не запускається від зміни лише серверного коду.

APK на телефон дозволений лише з чистої погодженої main із записом SHA-256
та перевіркою встановленого файла. У цьому PR main не змінюємо, Play-реліз
не публікуємо. Секретні локальні файли й кеші не копіювалися.
