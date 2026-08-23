# Release signing runbook

How the AvelRen Android app is signed for a Play Console upload. Closes the
signing half of #25.

## The upload key

The release/upload key is an RSA-4096 self-signed certificate valid for 25
years, in a PKCS12 keystore:

- **Keystore:** `C:/AI/keys/avelren-upload.jks` — **outside** the repository.
- **Alias:** `avelren-upload`
- **Store/key password:** identical; kept only in the operator's password
  manager, never in git, logs, or evidence.

The keystore was created with:

```bash
keytool -genkeypair -v -keystore C:/AI/keys/avelren-upload.jks \
  -alias avelren-upload -keyalg RSA -keysize 4096 -validity 9125 \
  -storepass <password> -keypass <password> \
  -dname "CN=AvelRen, O=AvelRen, C=UA"
```

> **Losing the upload key is recoverable but painful.** Google Play App Signing
> lets you reset a lost upload key through support, but it is a multi-day round
> trip. Keep a copy of `avelren-upload.jks` **and** its password in the password
> manager (attach the file), on separate media from the working machine.

## keystore.properties (gitignored)

Gradle reads the key location and passwords from `android/keystore.properties`.
It is listed in `.gitignore` (`keystore.properties`) and must never be
committed:

```properties
storeFile=C:/AI/keys/avelren-upload.jks
storePassword=<password>
keyAlias=avelren-upload
keyPassword=<password>
```

`app/build.gradle.kts` creates the `release` signing config **only if this file
exists**, so CI (which has no key) and any fresh clone still build a debug or
unsigned release without failing.

## Building the release AAB

The bundle for Play must come from a **clean `main`** (AGENTS.md rule 10):

```bash
git status                      # tree must be clean, on main
cd android
./gradlew bundleRelease
```

Output: `android/app/build/outputs/bundle/release/app-release.aab`, signed with
the upload key.

Record the build in `dist/BUILD.txt` (gitignored, AGENTS.md rule 10):

```
sha256  <sha256 of app-release.aab>
commit  <git rev-parse HEAD>
date    <UTC date>
```

`google-services.json` (real, from the Firebase console → project settings →
your apps) must be present in `android/app/` before the build — it is
deliberately not in git.

## Minify / R8 — deferred on purpose

The first release ships with `isMinifyEnabled = false` and
`isShrinkResources = false`. Reason: ktor, kotlinx.serialization and Firebase
all use reflection, and an R8 pass that strips or renames the wrong class
surfaces only at runtime, not at build time. The ProGuard rules for all three
are already staged in `app/proguard-rules.pro`.

To turn minify on later:

1. Flip `isMinifyEnabled = true` and `isShrinkResources = true` in
   `app/build.gradle.kts`.
2. Build `bundleRelease`, install the resulting APK/AAB on a real device.
3. Exercise **every** screen and flow — registration, checkpoint list,
   history/chart, thresholds, notifications. A missing keep-rule shows up as a
   serialization or reflection crash on a specific screen, not a build error.
4. Only if all screens pass, keep it on; otherwise add the missing keep rule or
   revert to `false`.

## Play App Signing

On the first upload, opt into **Play App Signing**: Google holds the app signing
key, and `avelren-upload.jks` becomes only the upload key. That is why losing the
upload key is recoverable — the app signing key never leaves Google.
