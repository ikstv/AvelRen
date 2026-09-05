package ua.avelren.app

import android.Manifest
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.core.app.ActivityCompat
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import kotlinx.coroutines.launch
import ua.avelren.app.data.DeviceStore
import ua.avelren.app.data.NotificationPermission
import ua.avelren.app.data.NotificationPermissionState
import ua.avelren.app.data.UiPrefs
import ua.avelren.app.notify.Notifications
import ua.avelren.app.ui.AvelRenScreen
import ua.avelren.app.ui.OnboardingScreen
import ua.avelren.app.ui.theme.AvelRenTheme

class MainActivity : ComponentActivity() {

    private var permissionState by mutableStateOf<NotificationPermissionState>(
        NotificationPermissionState.Granted
    )

    /**
     * #117: measured facts about background delivery, refreshed with the
     * permission on every onResume — a battery exemption can be granted or
     * revoked in system settings while we are in the background, exactly like the
     * permission itself.
     */
    private var ignoringBatteryOptimizations by mutableStateOf(true)
    private var backgroundHintDismissed by mutableStateOf(false)

    private val requestNotifications =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            // An empty callback previously meant no one saw the denial.
            // We read `shouldShowRequestPermissionRationale` specifically AFTER
            // the result: it distinguishes an explicit "Don't allow" (becomes true)
            // from a dialog dismissal (state unchanged — false); otherwise the very
            // first dismissal would look like a permanent denial.
            val rationaleNow = rationaleForNotifications()
            DeviceStore.saveNotificationHistory(
                this,
                NotificationPermission.afterRequest(
                    DeviceStore.notificationHistory(this), granted, rationaleNow
                ),
            )
            refreshPermissionState()
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Must run BEFORE refreshPermissionState/auto-request: for an upgrade from
        // a pre-AND-2 version it records the fact of the denial, otherwise onCreate
        // would again poke the launcher with a dead (no longer shown) dialog.
        migrateLegacyNotificationHistory()

        refreshPermissionState()

        // The initial request exactly once. Previously launch() was called on every
        // Activity creation: after two denials the system no longer shows the dialog,
        // so it was a silent no-op with no way back.
        if (permissionState is NotificationPermissionState.NeedsRequest &&
            !DeviceStore.notificationHistory(this).asked
        ) {
            launchRequest()
        }

        setContent {
            val ctx = LocalContext.current
            val onboardingSeen by UiPrefs.onboardingSeenFlow(ctx)
                .collectAsStateWithLifecycle(false)
            val scope = rememberCoroutineScope()
            AvelRenTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    if (!onboardingSeen) {
                        OnboardingScreen(
                            version = BuildConfig.VERSION_NAME,
                            onStart = { scope.launch { UiPrefs.setOnboardingSeen(ctx) } },
                        )
                    } else {
                        AvelRenScreen(
                            permissionState = permissionState,
                            onOpenNotificationSettings = { openNotificationSettings() },
                            ignoringBatteryOptimizations = ignoringBatteryOptimizations,
                            backgroundHintDismissed = backgroundHintDismissed,
                            onOpenBatterySettings = { openBatterySettings() },
                            onDismissBackgroundHint = {
                                DeviceStore.markBackgroundHintDismissed(this@MainActivity)
                                backgroundHintDismissed = true
                            },
                        )
                    }
                }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        // The permission may have been enabled in system settings or revoked —
        // the banner must disappear/appear without restarting the app.
        refreshPermissionState()
    }

    /**
     * One-time history migration for installations upgraded from a pre-AND-2
     * version (B2). We distinguish a fresh install from an upgrade via
     * PackageManager: on a clean install firstInstallTime == lastUpdateTime. Runs
     * exactly once — the persisted marker survives even a 401 re-registration.
     */
    private fun migrateLegacyNotificationHistory() {
        if (DeviceStore.notificationLegacyMigrated(this)) return
        val migrated = NotificationPermission.migrateLegacyHistory(
            sdkInt = Build.VERSION.SDK_INT,
            isUpgrade = appWasUpgraded(),
            runtimeGranted = Notifications.runtimePermissionGranted(this),
            history = DeviceStore.notificationHistory(this),
        )
        DeviceStore.saveNotificationHistory(this, migrated)
        DeviceStore.markNotificationLegacyMigrated(this)
    }

    /** true if the APK was updated over the installation at least once (not a fresh install). */
    private fun appWasUpgraded(): Boolean = runCatching {
        val info = packageManager.getPackageInfo(packageName, 0)
        info.lastUpdateTime > info.firstInstallTime
    }.getOrDefault(false)

    private fun refreshPermissionState() {
        val runtimeGranted = Notifications.runtimePermissionGranted(this)

        // Record an already-granted permission: after an APK update over an
        // installation where everything was allowed, the request callback never
        // fires, and a later revoke would look like "not asked yet". We write only
        // when something actually changed — to avoid poking storage on every onResume.
        val stored = DeviceStore.notificationHistory(this)
        val history = NotificationPermission.observeCurrentGrant(
            Build.VERSION.SDK_INT, runtimeGranted, stored
        )
        if (history != stored) DeviceStore.saveNotificationHistory(this, history)

        // #117. Measured, not guessed: this is a real API answer about this
        // installation. A failure to read it must not invent a problem, so the
        // fallback is "exempt" — the hint stays silent rather than crying wolf.
        ignoringBatteryOptimizations = runCatching {
            (getSystemService(POWER_SERVICE) as android.os.PowerManager)
                .isIgnoringBatteryOptimizations(packageName)
        }.getOrDefault(true)
        backgroundHintDismissed = DeviceStore.backgroundHintDismissed(this)

        permissionState = NotificationPermission.evaluate(
            sdkInt = Build.VERSION.SDK_INT,
            runtimeGranted = runtimeGranted,
            appNotificationsEnabled = Notifications.appNotificationsEnabled(this),
            alertChannelBlocked = Notifications.alertChannelBlocked(this),
            showRationale = rationaleForNotifications(),
            history = history,
        )
    }

    private fun rationaleForNotifications(): Boolean =
        Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ActivityCompat.shouldShowRequestPermissionRationale(
                this, Manifest.permission.POST_NOTIFICATIONS
            )

    private fun launchRequest() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            requestNotifications.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
    }

    /**
     * We lead exactly to where the problem is: a blocked alert channel — to the
     * channel settings, everything else — to the app's notification settings. The
     * general app screen with the channel disabled would force the user to find it manually.
     */
    private fun openNotificationSettings() {
        // minSdk 26 — channels always exist, a separate version check is not needed.
        val intent = if (permissionState is NotificationPermissionState.NeedsAlertChannelSettings) {
            Intent(Settings.ACTION_CHANNEL_NOTIFICATION_SETTINGS)
                .putExtra(Settings.EXTRA_APP_PACKAGE, packageName)
                .putExtra(Settings.EXTRA_CHANNEL_ID, Notifications.CHANNEL_ID)
        } else {
            Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                .putExtra(Settings.EXTRA_APP_PACKAGE, packageName)
        }
        runCatching { startActivity(intent) }.onFailure {
            // Rare firmware without this screen — open the app details page.
            runCatching { startActivity(appDetailsIntent()) }
        }
    }

    /**
     * #117: the battery-optimisation list.
     *
     * Deliberately ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS (the list) and not
     * ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS (the one-tap dialog): the latter
     * needs the REQUEST_IGNORE_BATTERY_OPTIMIZATIONS permission, which Google Play
     * only allows for a narrow set of app categories. This app is mid-review after
     * two policy rejections — a permission we would have to argue for is not a
     * trade worth making for one saved tap.
     *
     * On MIUI and its relatives the autostart list lives somewhere else entirely
     * and no documented intent opens it, so there the app details page is the
     * closest honest destination; the hint text names the setting to look for.
     */
    private fun openBatterySettings() {
        runCatching {
            startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
        }.onFailure {
            runCatching { startActivity(appDetailsIntent()) }
        }
    }

    private fun appDetailsIntent(): Intent = Intent(
        Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
        Uri.fromParts("package", packageName, null),
    )
}
