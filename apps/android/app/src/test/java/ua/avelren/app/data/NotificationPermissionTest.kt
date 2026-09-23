package ua.avelren.app.data

import org.junit.Assert.assertEquals
import org.junit.Test
import ua.avelren.app.data.NotificationPermission.History
import ua.avelren.app.data.NotificationPermissionState as S

/**
 * Pure notification-permission state logic (AND-2).
 *
 * We check not only the Android 13 runtime permission, but the whole path by
 * which an alert can silently fail to arrive: an app-wide notification block and a
 * blocked `avelren_alerts` channel (IMPORTANCE_NONE).
 */
class NotificationPermissionTest {

    private fun eval(
        sdk: Int = 33,
        runtimeGranted: Boolean = true,
        appEnabled: Boolean = true,
        channelBlocked: Boolean = false,
        rationale: Boolean = false,
        asked: Boolean = false,
        deniedOnce: Boolean = false,
        everGranted: Boolean = false,
    ) = NotificationPermission.evaluate(
        sdkInt = sdk,
        runtimeGranted = runtimeGranted,
        appNotificationsEnabled = appEnabled,
        alertChannelBlocked = channelBlocked,
        showRationale = rationale,
        history = History(asked = asked, deniedOnce = deniedOnce, everGranted = everGranted),
    )

    // --- runtime permission (API 33+) -------------------------------------

    @Test
    fun `granted runtime with everything enabled is Granted`() {
        assertEquals(S.Granted, eval(runtimeGranted = true))
    }

    @Test
    fun `not granted and never asked needs request`() {
        assertEquals(S.NeedsRequest, eval(runtimeGranted = false, asked = false))
    }

    @Test
    fun `not granted with rationale needs request`() {
        assertEquals(S.NeedsRequest, eval(runtimeGranted = false, asked = true, rationale = true))
    }

    @Test
    fun `denied once without rationale needs app settings`() {
        // A repeated/permanent denial — the dialog will no longer appear.
        assertEquals(
            S.NeedsAppSettings,
            eval(runtimeGranted = false, asked = true, deniedOnce = true, rationale = false),
        )
    }

    @Test
    fun `dialog swiped away is not punished with settings`() {
        // asked=true, but the user did not tap Deny (deniedOnce=false) and
        // rationale=false — this is a swipe-away, re-asking is allowed.
        assertEquals(
            S.NeedsRequest,
            eval(runtimeGranted = false, asked = true, deniedOnce = false, rationale = false),
        )
    }

    @Test
    fun `revoked after grant needs app settings`() {
        assertEquals(
            S.NeedsAppSettings,
            eval(runtimeGranted = false, asked = true, everGranted = true, rationale = false),
        )
    }

    // --- app-wide disabling (all APIs) -------------------------------------

    @Test
    fun `app notifications blocked below api 33 needs app settings`() {
        assertEquals(
            S.NeedsAppSettings,
            eval(sdk = 30, runtimeGranted = true, appEnabled = false),
        )
    }

    @Test
    fun `below api 33 with notifications enabled is Granted`() {
        assertEquals(S.Granted, eval(sdk = 30, runtimeGranted = false, appEnabled = true))
    }

    @Test
    fun `app notifications blocked outranks granted runtime permission`() {
        assertEquals(S.NeedsAppSettings, eval(runtimeGranted = true, appEnabled = false))
    }

    // --- blocked channel -----------------------------------------------

    @Test
    fun `blocked alert channel needs channel settings`() {
        assertEquals(
            S.NeedsAlertChannelSettings,
            eval(runtimeGranted = true, appEnabled = true, channelBlocked = true),
        )
    }

    @Test
    fun `blocked alert channel below api 33 needs channel settings`() {
        assertEquals(
            S.NeedsAlertChannelSettings,
            eval(sdk = 30, runtimeGranted = false, appEnabled = true, channelBlocked = true),
        )
    }

    @Test
    fun `app-wide block takes precedence over channel block`() {
        // No point leading to the channel if the whole app is blocked.
        assertEquals(
            S.NeedsAppSettings,
            eval(runtimeGranted = true, appEnabled = false, channelBlocked = true),
        )
    }

    // --- returning from Settings --------------------------------------------

    @Test
    fun `returning from settings with everything enabled is Granted`() {
        assertEquals(
            S.Granted,
            eval(
                runtimeGranted = true, appEnabled = true, channelBlocked = false,
                asked = true, deniedOnce = true, everGranted = true,
            ),
        )
    }

    // --- migration of an already-granted permission (upgrade install) ----------------

    @Test
    fun `existing install with granted permission seeds everGranted`() {
        // The history starts empty after an APK update over an installation where
        // the permission was already granted: the request callback never fires, so
        // the fact of the grant must be recorded from the actual state.
        val fresh = History()
        assertEquals(
            History(asked = false, deniedOnce = false, everGranted = true),
            NotificationPermission.observeCurrentGrant(33, runtimeGranted = true, history = fresh),
        )
    }

    @Test
    fun `existing grant then revoke needs app settings`() {
        // The end-to-end scenario for which the seeding is needed.
        val seeded = NotificationPermission.observeCurrentGrant(33, true, History())
        val afterRevoke = NotificationPermission.evaluate(
            sdkInt = 33,
            runtimeGranted = false,          // revoked in Settings
            appNotificationsEnabled = true,
            alertChannelBlocked = false,
            showRationale = false,
            history = seeded,
        )
        assertEquals(S.NeedsAppSettings, afterRevoke)  // and not NeedsRequest
    }

    @Test
    fun `grant in settings after deny seeds everGranted`() {
        val denied = History(asked = true, deniedOnce = true, everGranted = false)
        assertEquals(
            History(asked = true, deniedOnce = true, everGranted = true),
            NotificationPermission.observeCurrentGrant(33, runtimeGranted = true, history = denied),
        )
    }

    @Test
    fun `no seeding below api 33`() {
        // Below 33 runtimeGranted is synthesized as true (the runtime permission
        // does not exist) — this is NOT proof of a real grant, we must not seed from it.
        val fresh = History()
        assertEquals(
            fresh,
            NotificationPermission.observeCurrentGrant(30, runtimeGranted = true, history = fresh),
        )
    }

    @Test
    fun `no seeding when not granted`() {
        val fresh = History()
        assertEquals(
            fresh,
            NotificationPermission.observeCurrentGrant(33, runtimeGranted = false, history = fresh),
        )
    }

    // --- legacy migration (upgrade from a pre-AND-2 version) ----------------------

    @Test
    fun `legacy permanent denial upgrade migrates to denied and needs app settings`() {
        // An upgrade from a version where the old MainActivity asked on every start;
        // the user already refused twice → there will be no more dialog.
        val migrated = NotificationPermission.migrateLegacyHistory(
            sdkInt = 33, isUpgrade = true, runtimeGranted = false, history = History(),
        )
        assertEquals(History(asked = true, deniedOnce = true, everGranted = false), migrated)
        // rationale=false because the system no longer shows the dialog → we lead to
        // Settings instead of leaving a dead "Allow" button.
        assertEquals(
            S.NeedsAppSettings,
            eval(runtimeGranted = false, asked = true, deniedOnce = true, rationale = false),
        )
    }

    @Test
    fun `legacy single denial upgrade with rationale stays requestable`() {
        // The same migration, but the system is still ready to show the dialog (one denial):
        // the showRationale short-circuit in evaluate keeps NeedsRequest.
        val migrated = NotificationPermission.migrateLegacyHistory(
            sdkInt = 33, isUpgrade = true, runtimeGranted = false, history = History(),
        )
        assertEquals(
            S.NeedsRequest,
            eval(
                runtimeGranted = false,
                asked = migrated.asked, deniedOnce = migrated.deniedOnce, rationale = true,
            ),
        )
    }

    @Test
    fun `fresh install never asked is not migrated`() {
        // firstInstallTime == lastUpdateTime → isUpgrade=false: the history stays
        // empty, evaluate gives NeedsRequest, onCreate does one auto-request.
        val migrated = NotificationPermission.migrateLegacyHistory(
            sdkInt = 33, isUpgrade = false, runtimeGranted = false, history = History(),
        )
        assertEquals(History(), migrated)
        assertEquals(S.NeedsRequest, eval(runtimeGranted = false, asked = false))
    }

    @Test
    fun `fresh install swipe away is not turned into denial`() {
        // A swipe on a fresh install makes the history non-empty (asked=true) even
        // BEFORE any migration — so migrate leaves it unchanged instead of punishing with Settings.
        val swiped = History(asked = true, deniedOnce = false, everGranted = false)
        assertEquals(
            swiped,
            NotificationPermission.migrateLegacyHistory(
                sdkInt = 33, isUpgrade = true, runtimeGranted = false, history = swiped,
            ),
        )
        assertEquals(
            S.NeedsRequest,
            eval(runtimeGranted = false, asked = true, deniedOnce = false, rationale = false),
        )
    }

    @Test
    fun `upgrade with granted permission is left for seeding`() {
        // The migration does not touch a grant — that is observeCurrentGrant's job.
        assertEquals(
            History(),
            NotificationPermission.migrateLegacyHistory(
                sdkInt = 33, isUpgrade = true, runtimeGranted = true, history = History(),
            ),
        )
    }

    @Test
    fun `no legacy migration below api 33`() {
        assertEquals(
            History(),
            NotificationPermission.migrateLegacyHistory(
                sdkInt = 30, isUpgrade = true, runtimeGranted = false, history = History(),
            ),
        )
    }

    @Test
    fun `no legacy migration when history already tracked`() {
        // AND-2 already recorded something (e.g. everGranted after a grant) — do not overwrite.
        val tracked = History(asked = true, deniedOnce = false, everGranted = true)
        assertEquals(
            tracked,
            NotificationPermission.migrateLegacyHistory(
                sdkInt = 33, isUpgrade = true, runtimeGranted = false, history = tracked,
            ),
        )
    }

    // --- recording history ----------------------------------------------------

    @Test
    fun `explicit deny is recorded as deniedOnce`() {
        // An explicit "Don't allow" makes rationale=true right after the result.
        val h = History(asked = true, deniedOnce = false, everGranted = false)
        assertEquals(
            History(asked = true, deniedOnce = true, everGranted = false),
            NotificationPermission.afterRequest(h, granted = false, showRationaleNow = true),
        )
    }

    @Test
    fun `swiped away dialog is not recorded as denial`() {
        // A swipe does not change the permission state: rationale stays false — this
        // is NOT a denial, otherwise the very first swipe would send the user to Settings.
        val h = History(asked = true, deniedOnce = false, everGranted = false)
        assertEquals(
            History(asked = true, deniedOnce = false, everGranted = false),
            NotificationPermission.afterRequest(h, granted = false, showRationaleNow = false),
        )
    }

    @Test
    fun `history records grant as everGranted`() {
        val h = History(asked = true, deniedOnce = true, everGranted = false)
        assertEquals(
            History(asked = true, deniedOnce = true, everGranted = true),
            NotificationPermission.afterRequest(h, granted = true, showRationaleNow = false),
        )
    }
}
