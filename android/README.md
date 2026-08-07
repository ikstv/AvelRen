# AvelRen Android

## Збірка з чистого клону

Потрібні: JDK 17, Android SDK (platform 35).

1. **`google-services.json`** — не в git і не буде: він містить ідентифікатори
   Firebase-проєкту. Взяти з Firebase Console (Project settings → Your apps →
   AvelRen → google-services.json) і покласти в `android/app/`.
   Без нього збірка падає на плагіні Google Services — це очікувано.
2. `local.properties` створюється сам, або вручну:
   `sdk.dir=<шлях до Android SDK>` (прямі слеші працюють і на Windows).
3. Збірка: `./gradlew assembleDebug`
   APK: `app/build/outputs/apk/debug/app-debug.apk`

## Правило

Застосунок звертається **тільки** до нашого API (`api.bordersignal.pp.ua`).
Жодних запитів до echerha.gov.ua з клієнта — див. корінний `AGENTS.md`, правило 1.
