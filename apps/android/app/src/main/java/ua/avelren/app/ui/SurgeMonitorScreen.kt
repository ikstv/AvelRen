package ua.avelren.app.ui

import androidx.compose.runtime.Composable
import ua.avelren.app.data.SurgeMonitorClient

@Composable
fun SurgeMonitorScreen(
    repository: SurgeMonitorClient,
    onBack: () -> Unit,
    notificationsAllowed: Boolean = false,
    onOpenNotificationSettings: () -> Unit = {},
    onCountForecast: (Int) -> Unit = {},
    enqueueAck: ((Long) -> Unit)? = null,
    refreshVersion: Int = 0,
) {
    ForecastOverviewScreen(repository, onBack, notificationsAllowed, onOpenNotificationSettings, onCountForecast, enqueueAck, refreshVersion)
}
