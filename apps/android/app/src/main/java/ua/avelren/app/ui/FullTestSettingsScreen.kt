package ua.avelren.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material.icons.outlined.BatterySaver
import androidx.compose.material.icons.outlined.Code
import androidx.compose.material.icons.outlined.DarkMode
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material.icons.outlined.Notifications
import androidx.compose.material.icons.outlined.ScreenLockPortrait
import androidx.compose.material.icons.outlined.Share
import androidx.compose.material.icons.outlined.Shield
import androidx.compose.material.icons.outlined.StarOutline
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import ua.avelren.app.data.NotificationReadiness
import ua.avelren.app.ui.theme.AppAccent
import ua.avelren.app.ui.theme.AppBackground
import ua.avelren.app.ui.theme.AppInk
import ua.avelren.app.ui.theme.AppOnAccent
import ua.avelren.app.ui.theme.avelren
import ua.avelren.app.ui.theme.hapticClick
import ua.avelren.app.ui.theme.hapticToggle

/** Реальні налаштування FullTest; збереження стану та системні переходи виконує батьківський екран. */
@Composable
internal fun FullTestSettingsScreen(
    dark: Boolean,
    onToggleTheme: () -> Unit,
    keepScreenOn: Boolean,
    onKeepScreenOnChange: (Boolean) -> Unit,
    notificationsEnabled: Boolean,
    ignoringBatteryOptimizations: Boolean,
    onOpenNotificationSettings: () -> Unit,
    onOpenBatterySettings: () -> Unit,
    onShareApp: () -> Unit,
    onRateApp: () -> Unit,
    onOpenAbout: () -> Unit,
    onOpenPrivacy: () -> Unit,
    onOpenDeveloper: () -> Unit,
    modifier: Modifier = Modifier,
    notificationReadiness: NotificationReadiness.Result? = null,
) {
    Column(
        modifier = modifier.fillMaxWidth()
            .verticalScroll(rememberScrollState())
            .padding(vertical = 20.dp),
        verticalArrangement = Arrangement.spacedBy(20.dp),
    ) {
        FullTestSettingsGroup("Вигляд") {
            FullTestSettingsToggle(
                title = "Темна тема",
                subtitle = if (dark) "Чорна з жовтим" else "Світла з червоним",
                icon = Icons.Outlined.DarkMode,
                checked = dark,
                onCheckedChange = { onToggleTheme() },
            )
            FullTestSettingsDivider()
            FullTestSettingsToggle(
                title = "Не гасити екран",
                subtitle = "Лише коли додаток відкритий · витрачає більше заряду",
                icon = Icons.Outlined.ScreenLockPortrait,
                checked = keepScreenOn,
                onCheckedChange = onKeepScreenOnChange,
            )
        }
        FullTestSettingsGroup("Сповіщення") {
            FullTestSettingsAction(
                title = "Звук і сповіщення",
                subtitle = notificationReadiness?.let { "${it.title}. ${it.detail} Натисніть, щоб відкрити налаштування Android." } ?: if (notificationsEnabled) {
                    "Дозвіл Android надано · налаштувати звук"
                } else {
                    "Вимкнено в Android · відкрити налаштування"
                },
                icon = Icons.Outlined.Notifications,
                onClick = onOpenNotificationSettings,
            )
            notificationReadiness?.indicators?.forEach { indicator ->
                FullTestSettingsDivider()
                Column(
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    Text(
                        text = when (indicator.status) {
                            NotificationReadiness.Status.Observed -> indicator.title
                            NotificationReadiness.Status.Attention -> "Увага · ${indicator.title}"
                            NotificationReadiness.Status.Unknown -> "Невідомо · ${indicator.title}"
                        },
                        style = MaterialTheme.typography.labelLarge,
                        color = if (indicator.status == NotificationReadiness.Status.Attention) AppAccent else AppInk,
                    )
                    Text(indicator.detail, color = MaterialTheme.avelren.ink2, style = MaterialTheme.typography.bodySmall)
                }
            }
            FullTestSettingsDivider()
            FullTestSettingsAction(
                title = "Фонова робота",
                subtitle = if (ignoringBatteryOptimizations) {
                    "Стандартна оптимізація батареї Android вимкнена"
                } else {
                    "Android може обмежувати роботу у фоні"
                },
                icon = Icons.Outlined.BatterySaver,
                onClick = onOpenBatterySettings,
            )
        }
        FullTestSettingsGroup("Підтримати додаток") {
            FullTestSettingsAction(
                title = "Поділитися додатком",
                subtitle = "Посилання на офіційну версію",
                icon = Icons.Outlined.Share,
                onClick = onShareApp,
            )
            FullTestSettingsDivider()
            FullTestSettingsAction(
                title = "Оцінити додаток",
                subtitle = "Офіційна версія в Google Play",
                icon = Icons.Outlined.StarOutline,
                onClick = onRateApp,
            )
        }
        FullTestSettingsGroup("Інформація") {
            FullTestSettingsAction(
                title = "Про додаток",
                icon = Icons.Outlined.Info,
                onClick = onOpenAbout,
            )
            FullTestSettingsDivider()
            FullTestSettingsAction(
                title = "Конфіденційність",
                icon = Icons.Outlined.Shield,
                onClick = onOpenPrivacy,
            )
            FullTestSettingsDivider()
            FullTestSettingsAction(
                title = "Для розробника",
                icon = Icons.Outlined.Code,
                onClick = onOpenDeveloper,
            )
        }
    }
}

@Composable
private fun FullTestSettingsGroup(title: String, content: @Composable ColumnScope.() -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text(
            text = title,
            color = MaterialTheme.avelren.ink2,
            style = MaterialTheme.typography.labelLarge,
            modifier = Modifier.padding(horizontal = 12.dp).semantics { heading() },
        )
        Column(
            modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(20.dp))
                .background(MaterialTheme.colorScheme.surfaceVariant),
            content = content,
        )
    }
}

@Composable
private fun FullTestSettingsAction(
    title: String,
    icon: ImageVector,
    onClick: () -> Unit,
    subtitle: String? = null,
) {
    Row(
        modifier = Modifier.fillMaxWidth().heightIn(min = 64.dp)
            .semantics(mergeDescendants = true) { }
            .clickable(role = Role.Button, onClick = hapticClick(onClick))
            .padding(horizontal = 16.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Icon(icon, contentDescription = null, modifier = Modifier.size(24.dp), tint = AppAccent)
        FullTestSettingsLabel(title, subtitle, Modifier.weight(1f))
        Icon(
            imageVector = Icons.AutoMirrored.Filled.KeyboardArrowRight,
            contentDescription = null,
            modifier = Modifier.size(20.dp),
            tint = MaterialTheme.avelren.ink2,
        )
    }
}

@Composable
private fun FullTestSettingsToggle(
    title: String,
    subtitle: String,
    icon: ImageVector,
    checked: Boolean,
    onCheckedChange: (Boolean) -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth().heightIn(min = 72.dp)
            .toggleable(value = checked, role = Role.Switch, onValueChange = hapticToggle(onCheckedChange))
            .padding(horizontal = 16.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Icon(icon, contentDescription = null, modifier = Modifier.size(24.dp), tint = AppAccent)
        FullTestSettingsLabel(title, subtitle, Modifier.weight(1f))
        Switch(
            checked = checked,
            onCheckedChange = null,
            modifier = Modifier.clearAndSetSemantics { },
            colors = SwitchDefaults.colors(
                checkedThumbColor = AppOnAccent,
                checkedTrackColor = AppAccent,
                checkedBorderColor = AppAccent,
                uncheckedThumbColor = MaterialTheme.avelren.ink2,
                uncheckedTrackColor = AppBackground,
                uncheckedBorderColor = MaterialTheme.avelren.line,
            ),
        )
    }
}

@Composable
private fun FullTestSettingsLabel(title: String, subtitle: String?, modifier: Modifier) {
    Column(modifier, verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(
            text = title,
            color = AppInk,
            style = MaterialTheme.typography.bodyLarge.copy(fontWeight = FontWeight.Bold),
        )
        if (subtitle != null) {
            Text(text = subtitle, color = MaterialTheme.avelren.ink2, style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
private fun FullTestSettingsDivider() {
    HorizontalDivider(
        modifier = Modifier.padding(start = 54.dp, end = 16.dp),
        color = MaterialTheme.avelren.line,
        thickness = 0.5.dp,
    )
}
