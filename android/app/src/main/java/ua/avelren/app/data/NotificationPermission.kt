package ua.avelren.app.data

/**
 * What exactly prevents an alert from reaching the user (AND-2).
 *
 * The catch is that "notification permission" is not a single flag. An alert will
 * silently fail to appear in at least three cases: no runtime permission
 * (Android 13+), the app's notifications are disabled in the system, or the
 * `avelren_alerts` channel itself is blocked. For a service whose whole point is
 * to wake the driver, each of these is critical, so we lead the user to the right
 * place instead of showing one generic error.
 */
sealed interface NotificationPermissionState {
    /** All is well: the alert will actually appear. */
    data object Granted : NotificationPermissionState

    /** The system request dialog can be shown. */
    data object NeedsRequest : NotificationPermissionState

    /** The dialog will no longer appear — only the app settings. */
    data object NeedsAppSettings : NotificationPermissionState

    /** The app is allowed, but the alert channel is disabled — we lead to the channel. */
    data object NeedsAlertChannelSettings : NotificationPermissionState
}

/**
 * Pure permission-state logic — without Android dependencies, so fully testable
 * on the JVM. The caller passes facts (SDK, permission, `areNotificationsEnabled()`,
 * channel importance, `shouldShowRequestPermissionRationale`) and the persisted
 * history.
 */
object NotificationPermission {

    /**
     * Persisted request history. `asked` alone is not enough: the user can
     * dismiss the dialog without choosing anything — then the permission state
     * does not change, and "asked without rationale" would mistakenly look like a
     * permanent denial. So we record an explicit denial separately.
     */
    data class History(
        val asked: Boolean = false,
        val deniedOnce: Boolean = false,
        val everGranted: Boolean = false,
    )

    /** Since Android 13, showing notifications is the POST_NOTIFICATIONS runtime permission. */
    const val RUNTIME_PERMISSION_SDK = 33

    fun evaluate(
        sdkInt: Int,
        runtimeGranted: Boolean,
        appNotificationsEnabled: Boolean,
        alertChannelBlocked: Boolean,
        showRationale: Boolean,
        history: History,
    ): NotificationPermissionState {
        // 1. Runtime permission (only 33+). Without it the rest does not matter.
        if (sdkInt >= RUNTIME_PERMISSION_SDK && !runtimeGranted) {
            return when {
                // Permission was there and is gone — no more dialog, only Settings.
                history.everGranted -> NotificationPermissionState.NeedsAppSettings
                // Not asked yet, or the system is ready to show the dialog again.
                !history.asked || showRationale -> NotificationPermissionState.NeedsRequest
                // Explicitly denied and rationale is no longer offered → permanent.
                history.deniedOnce -> NotificationPermissionState.NeedsAppSettings
                // asked, but without an explicit denial — this is a dialog dismissal. We do not punish it.
                else -> NotificationPermissionState.NeedsRequest
            }
        }

        // 2. The app's notifications are disabled in the system. Applies to ALL versions:
        //    on 8–12 there is no runtime permission, and without this check the app
        //    would think all is well while the pushes go into the void.
        if (!appNotificationsEnabled) return NotificationPermissionState.NeedsAppSettings

        // 3. The app is allowed, but the alert channel itself is blocked
        //    (IMPORTANCE_NONE) — we lead straight to the channel settings.
        if (alertChannelBlocked) return NotificationPermissionState.NeedsAlertChannelSettings

        return NotificationPermissionState.Granted
    }

    /**
     * Records the fact of an **already-granted** permission in the history.
     *
     * `everGranted` is otherwise written only in the request callback — and that
     * never fires if the permission was granted before this code existed (an APK
     * update over an installation where everything was already allowed) or through
     * system settings. Then a later revoke would look like "never asked at all" and
     * lead to NeedsRequest instead of NeedsAppSettings — that is, exactly the
     * scenario AND-2 was meant to close would not work for existing installations.
     *
     * Below API 33 `runtimeGranted` is synthesized as `true` (the runtime
     * permission does not exist), so we must not seed from it — it is not proof of
     * a real grant.
     *
     * Returns the same history if there is nothing to change — the caller uses
     * this to understand that there is no need to write to storage.
     */
    fun observeCurrentGrant(
        sdkInt: Int,
        runtimeGranted: Boolean,
        history: History,
    ): History =
        if (sdkInt >= RUNTIME_PERMISSION_SDK && runtimeGranted && !history.everGranted) {
            history.copy(everGranted = true)
        } else {
            history
        }

    /**
     * One-time history migration for installations upgraded from a version BEFORE AND-2.
     *
     * The old `MainActivity` unconditionally called `launch(POST_NOTIFICATIONS)` on
     * every `onCreate`. So an existing user who already refused before AND-2 has,
     * after the APK update, `runtimeGranted=false` but an empty new AND-2 history.
     * `observeCurrentGrant()` seeds nothing here (permission is not granted), and
     * `evaluate()` without this migration treats `!asked` as `NeedsRequest`, after
     * which `onCreate` pokes the launcher again — but the system dialog no longer
     * appears after repeated Deny. The user would be stuck on the "Allow" button,
     * which in fact cures nothing.
     *
     * The fresh-install / upgrade distinction is passed from outside (`isUpgrade`) —
     * the caller takes it from `PackageManager` (firstInstallTime != lastUpdateTime).
     * A fresh install we leave with an empty history → `NeedsRequest` and a one-time
     * auto-request. For an upgrade with an EMPTY AND-2 history and `!runtimeGranted`
     * on API 33+, the fact of a denial is guaranteed (the legacy code definitely
     * asked), so we record `asked=true, deniedOnce=true`. From there the existing
     * `showRationale` short-circuit in `evaluate()` itself separates a recoverable
     * single-denial (rationale=true → `NeedsRequest`) from a permanent denial
     * (rationale=false → `NeedsAppSettings`).
     *
     * Runs exactly once (the caller holds a persisted marker). If the history is
     * already NOT empty — AND-2 keeps track itself, touch nothing. We do not seed
     * the grant here: that is `observeCurrentGrant()`'s job.
     */
    fun migrateLegacyHistory(
        sdkInt: Int,
        isUpgrade: Boolean,
        runtimeGranted: Boolean,
        history: History,
    ): History = when {
        history != History() -> history          // AND-2 already keeps track
        !isUpgrade -> history                     // fresh install — nothing to migrate
        sdkInt < RUNTIME_PERMISSION_SDK -> history // no runtime permission
        runtimeGranted -> history                 // observeCurrentGrant will seed the grant
        else -> History(asked = true, deniedOnce = true)
    }

    /**
     * Updating the history by the result of the system dialog.
     *
     * `showRationaleNow` is read AFTER the result — it is what distinguishes an
     * explicit denial (rationale becomes true) from a dialog dismissal (the state
     * did not change, so rationale stays false).
     */
    fun afterRequest(
        history: History,
        granted: Boolean,
        showRationaleNow: Boolean,
    ): History = history.copy(
        asked = true,
        deniedOnce = history.deniedOnce || (!granted && showRationaleNow),
        everGranted = history.everGranted || granted,
    )
}
