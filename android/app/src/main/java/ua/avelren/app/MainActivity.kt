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
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.core.app.ActivityCompat
import ua.avelren.app.data.DeviceStore
import ua.avelren.app.data.NotificationPermission
import ua.avelren.app.data.NotificationPermissionState
import ua.avelren.app.notify.Notifications
import ua.avelren.app.ui.AvelRenScreen

class MainActivity : ComponentActivity() {

    private var permissionState by mutableStateOf<NotificationPermissionState>(
        NotificationPermissionState.Granted
    )

    private val requestNotifications =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            // Порожній callback раніше означав, що відмову ніхто не бачив.
            // `shouldShowRequestPermissionRationale` читаємо саме ПІСЛЯ
            // результату: він відрізняє явний «Don't allow» (стає true) від
            // змаху діалогу (стан не змінився — false), інакше перший же змах
            // виглядав би як permanent denial.
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

        refreshPermissionState()

        // Первинний запит рівно один раз. Раніше launch() викликався на кожному
        // створенні Activity: після двох відмов система вже не показує діалог,
        // тож це був тихий no-op без жодного шляху назад.
        if (permissionState is NotificationPermissionState.NeedsRequest &&
            !DeviceStore.notificationHistory(this).asked
        ) {
            launchRequest()
        }

        setContent {
            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    AvelRenScreen(
                        permissionState = permissionState,
                        onRequestPermission = ::launchRequest,
                        onOpenSettings = ::openNotificationSettings,
                    )
                }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        // Дозвіл могли увімкнути в системних налаштуваннях або відкликати —
        // банер має зникнути/з'явитися без перезапуску застосунку.
        refreshPermissionState()
    }

    private fun refreshPermissionState() {
        val runtimeGranted = Notifications.runtimePermissionGranted(this)

        // Фіксуємо вже виданий дозвіл: після оновлення APK поверх установки, де
        // все було дозволено, callback запиту не спрацює ніколи, і пізніший
        // revoke виглядав би як «ще не питали». Пишемо лише коли реально
        // змінилось — щоб не смикати сховище на кожному onResume.
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
     * Ведемо саме туди, де проблема: заблокований канал алертів — у налаштування
     * каналу, все інше — у налаштування сповіщень застосунку. Загальний екран
     * застосунку при вимкненому каналі змусив би шукати його вручну.
     */
    private fun openNotificationSettings() {
        // minSdk 26 — канали існують завжди, окрема перевірка версії не потрібна.
        val intent = if (permissionState is NotificationPermissionState.NeedsAlertChannelSettings) {
            Intent(Settings.ACTION_CHANNEL_NOTIFICATION_SETTINGS)
                .putExtra(Settings.EXTRA_APP_PACKAGE, packageName)
                .putExtra(Settings.EXTRA_CHANNEL_ID, Notifications.CHANNEL_ID)
        } else {
            Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                .putExtra(Settings.EXTRA_APP_PACKAGE, packageName)
        }
        runCatching { startActivity(intent) }.onFailure {
            // Рідкісні прошивки без цього екрана — відкриваємо картку застосунку.
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
