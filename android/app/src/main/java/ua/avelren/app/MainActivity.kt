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
import ua.avelren.app.data.ThemePrefs
import ua.avelren.app.notify.Notifications
import ua.avelren.app.ui.AvelRenScreen
import ua.avelren.app.ui.OnboardingScreen
import ua.avelren.app.ui.theme.AvelRenTheme
import ua.avelren.app.ui.theme.ThemeMode

class MainActivity : ComponentActivity() {

    private var permissionState by mutableStateOf<NotificationPermissionState>(
        NotificationPermissionState.Granted
    )

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
            val mode by ThemePrefs.themeModeFlow(ctx)
                .collectAsStateWithLifecycle(ThemeMode.SYSTEM)
            val onboardingSeen by ThemePrefs.onboardingSeenFlow(ctx)
                .collectAsStateWithLifecycle(false)
            val scope = rememberCoroutineScope()
            AvelRenTheme(mode) {
                Surface(modifier = Modifier.fillMaxSize()) {
                    if (!onboardingSeen) {
                        OnboardingScreen(
                            version = BuildConfig.VERSION_NAME,
                            onStart = { scope.launch { ThemePrefs.setOnboardingSeen(ctx) } },
                        )
                    } else {
                        AvelRenScreen(
                            permissionState = permissionState,
                            onRequestPermission = ::launchRequest,
                            onOpenSettings = ::openNotificationSettings,
                            themeMode = mode,
                            onThemeChange = { scope.launch { ThemePrefs.setThemeMode(ctx, it) } },
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
            runCatching {
                startActivity(
                    Intent(
                        Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                        Uri.fromParts("package", packageName, null),
                    )
                )
            }
        }
    }
}
