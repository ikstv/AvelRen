# AvelRen Android

## Building from a clean clone

Requirements: JDK 17, Android SDK (platform 36 — compileSdk/targetSdk are 36).

1. **`google-services.json`** — not in git and never will be: it contains the
   Firebase project identifiers. Get it from the Firebase Console (Project
   settings → Your apps → AvelRen → google-services.json) and put it in
   `android/app/`. Without it the build fails on the Google Services plugin —
   this is expected.
2. `local.properties` is created automatically, or manually:
   `sdk.dir=<path to the Android SDK>` (forward slashes work on Windows too).
3. Build: `./gradlew assembleDebug`
   APK: `app/build/outputs/apk/debug/app-debug.apk`

## Runtime check on Android 16 (API 36)

`targetSdk 36` activates Android 16 runtime behaviors (forced edge-to-edge,
predictive back, orientation on wide screens) that a passing build does **not**
prove. To verify on an emulator (FCM is not needed for layout/edge-to-edge):

    sdkmanager "platforms;android-36" "system-images;android-36;google_apis;x86_64"
    avdmanager create avd -n api36 -k "system-images;android-36;google_apis;x86_64"

Then install the debug APK and walk the screens for edge-to-edge insets,
predictive back, and rotation/large-screen layout.

## Rule

The app talks **only** to our API (`api.bordersignal.pp.ua`).
No requests to the upstream source from the client — see the root `AGENTS.md`,
rule 1.
