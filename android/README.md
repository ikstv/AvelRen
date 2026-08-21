# AvelRen Android

## Building from a clean clone

Requirements: JDK 17, Android SDK (platform 35).

1. **`google-services.json`** — not in git and never will be: it contains the
   Firebase project identifiers. Get it from the Firebase Console (Project
   settings → Your apps → AvelRen → google-services.json) and put it in
   `android/app/`. Without it the build fails on the Google Services plugin —
   this is expected.
2. `local.properties` is created automatically, or manually:
   `sdk.dir=<path to the Android SDK>` (forward slashes work on Windows too).
3. Build: `./gradlew assembleDebug`
   APK: `app/build/outputs/apk/debug/app-debug.apk`

## Rule

The app talks **only** to our API (`api.bordersignal.pp.ua`).
No requests to echerha.gov.ua from the client — see the root `AGENTS.md`, rule 1.
