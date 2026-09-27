# Connected test APK

The connected test APK exists for controlled device checks against the real
AvelRen API without replacing the Play-installed application.

Build it only from a clean `main`:

```text
cd apps/android
./gradlew -PavelrenConnectedTest=true :app:assembleDebug
```

The resulting package is `ua.avelren.app.connectedtest`, its visible name is
`AvelRen — тест`, and it launches the same `MainActivity` as the production
application. It retains `INTERNET` and `ACCESS_NETWORK_STATE`, so public status
and workload flows use the configured AvelRen API.

Push registration is deliberately disabled. The connected test package has no
Firebase initializer, messaging service, acknowledgement receiver, or
notification permission. This prevents a test install from creating a second
production device identity while preserving the public server-status flow that
is needed for maintenance and reboot-banner acceptance testing.

This mode and the offline `avelrenUiPreview` mode are mutually exclusive. The
preview remains a static, server-free design surface; it must not be used as
evidence for API or reboot-banner behavior.

The current revision also keeps the earlier release-signing and Play-update
changes documented in `RELEASE-0.1.2-DRAFT.md` and `PLAY-UPDATES.md`.
