package ua.avelren.app.ui

import android.graphics.Color as AndroidColor
import android.view.WindowManager
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.MutableTransitionState
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.snap
import androidx.compose.animation.core.tween
import androidx.compose.animation.core.updateTransition
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.WindowInsetsSides
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.only
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.outlined.Code
import androidx.compose.material.icons.outlined.DarkMode
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material.icons.outlined.Insights
import androidx.compose.material.icons.outlined.LightMode
import androidx.compose.material.icons.outlined.Notifications
import androidx.compose.material.icons.outlined.Place
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Schedule
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material.icons.outlined.Shield
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.isTraversalGroup
import androidx.compose.ui.semantics.paneTitle
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.compose.ui.window.DialogWindowProvider
import androidx.core.view.WindowCompat
import ua.avelren.app.BuildConfig
import ua.avelren.app.R
import ua.avelren.app.data.ServerStatus
import ua.avelren.app.ui.theme.AppAccent
import ua.avelren.app.ui.theme.AppBackground
import ua.avelren.app.ui.theme.AppInk
import ua.avelren.app.ui.theme.AppOnAccent
import ua.avelren.app.ui.theme.LocalThemeChoice
import ua.avelren.app.ui.theme.ThemeChoice
import ua.avelren.app.ui.theme.avelren
import ua.avelren.app.ui.theme.hapticClick

internal enum class FullTestDestination {
    HOME, MONITOR, FORECAST, SETTINGS, NOTIFICATIONS, THEME, ABOUT, PRIVACY, DEVELOPER,
}

private data class DrawerColors(
    val panel: Color,
    val group: Color,
    val text: Color,
    val secondary: Color,
    val divider: Color,
    val accent: Color,
    val onAccent: Color,
)

@Composable
private fun drawerColors(): DrawerColors = DrawerColors(
    panel = AppBackground,
    group = MaterialTheme.colorScheme.surfaceVariant,
    text = AppInk,
    secondary = MaterialTheme.avelren.ink2,
    divider = MaterialTheme.avelren.line,
    accent = AppAccent,
    onAccent = AppOnAccent,
)

/** Тестова навігація. Окреме modal-вікно ізолює фокус і Back від вмісту під ним. */
@Composable
internal fun FullTestNavigationDrawer(
    open: Boolean,
    selected: FullTestDestination?,
    checkpointTitle: String?,
    serverStatus: ServerStatus,
    refreshing: Boolean,
    canChooseCheckpoint: Boolean,
    monitorCount: Int?,
    onClose: () -> Unit,
    onSelect: (FullTestDestination) -> Unit,
    onChooseCheckpoint: () -> Unit,
    onRefresh: () -> Unit,
    onToggleTheme: () -> Unit,
) {
    val visibility = remember { MutableTransitionState(false) }
    visibility.targetState = open
    val transition = updateTransition(visibility, label = "FullTest drawer")
    val progress by transition.animateFloat(
        transitionSpec = { tween(durationMillis = 300, easing = FastOutSlowInEasing) },
        label = "Drawer reveal",
    ) { visible -> if (visible) 1f else 0f }

    // Keep the modal window alive until its exit animation has finished.
    if (!visibility.currentState && !visibility.targetState && visibility.isIdle) return

    val colors = drawerColors()
    val dark = LocalThemeChoice.current != ThemeChoice.LIGHT
    val latestClose by rememberUpdatedState(onClose)
    Dialog(
        onDismissRequest = onClose,
        properties = DialogProperties(
            dismissOnBackPress = true,
            dismissOnClickOutside = false,
            // Compose 1.7 measures both axes from Configuration when this is false,
            // which can exceed the visible dialog area on Android 15. MATCH_PARENT
            // below supplies the width; keep the parent's real height constraints.
            usePlatformDefaultWidth = true,
            decorFitsSystemWindows = false,
        ),
    ) {
        val view = LocalView.current
        DisposableEffect(view, dark) {
            (view.parent as? DialogWindowProvider)?.window?.let { window ->
                // The animated Compose scrim is the only dim layer.
                window.clearFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND)
                window.setDimAmount(0f)
                window.setLayout(
                    WindowManager.LayoutParams.MATCH_PARENT,
                    WindowManager.LayoutParams.MATCH_PARENT,
                )
                @Suppress("DEPRECATION")
                window.statusBarColor = AndroidColor.TRANSPARENT
                @Suppress("DEPRECATION")
                window.navigationBarColor = AndroidColor.TRANSPARENT
                WindowCompat.getInsetsController(window, view).apply {
                    isAppearanceLightStatusBars = !dark
                    isAppearanceLightNavigationBars = !dark
                }
            }
            onDispose { }
        }

        BoxWithConstraints(Modifier.fillMaxSize()) {
            val panelWidth = minOf(maxWidth * 0.865f, 360.dp)
            val density = LocalDensity.current
            val panelWidthPx = with(density) { panelWidth.toPx() }
            val swipeThresholdPx = with(density) { 72.dp.toPx() }
            var dragOffsetPx by remember { mutableFloatStateOf(0f) }
            var dragging by remember { mutableStateOf(false) }
            val displayedDragOffset by animateFloatAsState(
                targetValue = dragOffsetPx,
                animationSpec = if (dragging) snap() else tween(180),
                label = "Drawer swipe",
            )
            LaunchedEffect(open) {
                if (open) {
                    dragging = false
                    dragOffsetPx = 0f
                }
            }

            Box(
                Modifier.fillMaxSize()
                    .background(Color.Black.copy(alpha = 0.56f * progress))
                    .semantics { contentDescription = "Закрити меню" }
                    .clickable(
                        enabled = open,
                        role = Role.Button,
                        onClickLabel = "Закрити меню",
                        onClick = onClose,
                        indication = null,
                        interactionSource = null,
                    ),
            )
            Column(
                modifier = Modifier.width(panelWidth).fillMaxHeight()
                    .graphicsLayer {
                        translationX = -panelWidthPx * (1f - progress) + displayedDragOffset * progress
                    }
                    .clip(RoundedCornerShape(topEnd = 32.dp, bottomEnd = 32.dp))
                    .background(colors.panel)
                    .pointerInput(panelWidthPx, swipeThresholdPx) {
                        detectHorizontalDragGestures(
                            onDragStart = { dragging = true },
                            onDragCancel = {
                                dragging = false
                                dragOffsetPx = 0f
                            },
                            onDragEnd = {
                                dragging = false
                                if (dragOffsetPx <= -swipeThresholdPx) latestClose()
                                else dragOffsetPx = 0f
                            },
                        ) { change, amount ->
                            change.consume()
                            dragOffsetPx = (dragOffsetPx + amount).coerceIn(-panelWidthPx, 0f)
                        }
                    }
                    .semantics {
                        paneTitle = "Меню AvelRen"
                        isTraversalGroup = true
                    }
                    .windowInsetsPadding(
                        WindowInsets.safeDrawing.only(WindowInsetsSides.Vertical + WindowInsetsSides.Start),
                    )
                    .padding(horizontal = 12.dp),
            ) {
                DrawerHeader(colors = colors, onClose = onClose)
                BoxWithConstraints(Modifier.weight(1f).fillMaxWidth()) {
                    // Footer stays at the bottom when everything fits, and joins
                    // the scroll content on short screens or with larger fonts.
                    Column(
                        Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).heightIn(min = maxHeight),
                        verticalArrangement = Arrangement.SpaceBetween,
                    ) {
                        Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                            DrawerCheckpointCard(
                                checkpointTitle = checkpointTitle,
                                status = serverStatus,
                                refreshing = refreshing,
                                canChooseCheckpoint = open && canChooseCheckpoint,
                                canRefresh = open && !refreshing,
                                colors = colors,
                                onChooseCheckpoint = {
                                    onClose()
                                    onChooseCheckpoint()
                                },
                                onRefresh = onRefresh,
                            )
                            DrawerSection("ОГЛЯД", colors) {
                                DrawerGroup(colors) {
                                    DrawerRow(FullTestDestination.HOME, "Головна",
                                        Icons.Outlined.Home, selected, open, colors, onClose, onSelect)
                                    DrawerDivider(colors)
                                    DrawerRow(FullTestDestination.MONITOR, "Моніторинг",
                                        Icons.Outlined.Schedule, selected, open, colors, onClose, onSelect,
                                        badgeCount = monitorCount?.takeIf { it >= 0 })
                                    DrawerDivider(colors)
                                    DrawerRow(FullTestDestination.FORECAST, "Прогноз черги",
                                        Icons.Outlined.Insights, selected, open, colors, onClose, onSelect)
                                }
                            }
                            DrawerSection("НАЛАШТУВАННЯ", colors) {
                                DrawerGroup(colors) {
                                    DrawerRow(FullTestDestination.SETTINGS, "Налаштування",
                                        Icons.Outlined.Settings, selected, open, colors, onClose, onSelect)
                                    DrawerDivider(colors)
                                    DrawerRow(FullTestDestination.NOTIFICATIONS, "Сповіщення",
                                        Icons.Outlined.Notifications, selected, open, colors, onClose, onSelect)
                                    DrawerDivider(colors)
                                    DrawerThemeToggle(dark = dark, enabled = open, colors = colors,
                                        onToggleTheme = onToggleTheme)
                                }
                            }
                            DrawerSection("ПРО ЗАСТОСУНОК", colors) {
                                DrawerGroup(colors) {
                                    DrawerRow(FullTestDestination.ABOUT, "Про застосунок",
                                        Icons.Outlined.Info, selected, open, colors, onClose, onSelect)
                                    DrawerDivider(colors)
                                    DrawerRow(FullTestDestination.PRIVACY, "Політика конфіденційності",
                                        Icons.Outlined.Shield, selected, open, colors, onClose, onSelect)
                                    DrawerDivider(colors)
                                    DrawerRow(FullTestDestination.DEVELOPER, "Для розробника",
                                        Icons.Outlined.Code, selected, open, colors, onClose, onSelect)
                                }
                            }
                            Spacer(Modifier.height(4.dp))
                        }
                        Column(
                            Modifier.padding(horizontal = 12.dp, vertical = 12.dp),
                            verticalArrangement = Arrangement.spacedBy(4.dp),
                        ) {
                            Text("Developer: Tanko Viktor", color = colors.text,
                                style = MaterialTheme.typography.bodySmall)
                            Text("Версія ${BuildConfig.VERSION_NAME} · FullTest", color = colors.secondary,
                                style = MaterialTheme.typography.bodySmall)
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun DrawerHeader(colors: DrawerColors, onClose: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().padding(start = 8.dp, end = 2.dp, top = 8.dp, bottom = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Image(
            painter = painterResource(R.drawable.ic_launcher_foreground),
            contentDescription = null,
            modifier = Modifier.size(48.dp).clip(RoundedCornerShape(14.dp))
                .background(Color.Black),
        )
        Column(Modifier.weight(1f)) {
            Text("AvelRen", color = colors.text, fontSize = 24.sp,
                fontWeight = FontWeight.Black, style = MaterialTheme.typography.titleLarge)
            Text("Черги на кордоні", color = colors.secondary, fontSize = 12.sp,
                style = MaterialTheme.typography.bodySmall)
        }
        IconButton(
            onClick = hapticClick(onClose),
            modifier = Modifier.size(48.dp).clip(CircleShape).background(colors.group),
        ) {
            Icon(Icons.Filled.Close, "Закрити меню", tint = colors.secondary, modifier = Modifier.size(24.dp))
        }
    }
}

@Composable
private fun DrawerCheckpointCard(
    checkpointTitle: String?,
    status: ServerStatus,
    refreshing: Boolean,
    canChooseCheckpoint: Boolean,
    canRefresh: Boolean,
    colors: DrawerColors,
    onChooseCheckpoint: () -> Unit,
    onRefresh: () -> Unit,
) {
    val shape = RoundedCornerShape(20.dp)
    val fullTitle = checkpointTitle?.takeIf { it.isNotBlank() } ?: "Оберіть пункт пропуску"
    val checkpointLabel = fullTestCheckpointLabel(fullTitle)
    Column(
        Modifier.fillMaxWidth().clip(shape).background(colors.group)
            .border(1.dp, colors.accent.copy(alpha = 0.5f), shape)
            .padding(horizontal = 12.dp, vertical = 10.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Text("ОБРАНИЙ КПП", color = colors.accent, style = MaterialTheme.typography.labelSmall)
        Column(
            Modifier.clearAndSetSemantics { contentDescription = fullTitle },
            verticalArrangement = Arrangement.spacedBy(2.dp),
        ) {
            Text(
                text = checkpointLabel.name,
                color = colors.text,
                style = MaterialTheme.typography.titleMedium,
                fontSize = 14.sp,
                lineHeight = 18.sp,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
            checkpointLabel.vehicleCategory?.let { category ->
                // Vehicle limits and cargo restrictions must remain readable in full.
                Text(category, color = colors.secondary, style = MaterialTheme.typography.bodySmall,
                    fontSize = 11.sp, lineHeight = 14.sp)
            }
        }
        if (status.label.isNotBlank() || status == ServerStatus.CHECKING) {
            val statusColor = when (status) {
                ServerStatus.ONLINE -> MaterialTheme.avelren.go
                ServerStatus.NO_INTERNET -> MaterialTheme.avelren.closed
                ServerStatus.WEAK_INTERNET, ServerStatus.MAINTENANCE, ServerStatus.RESTARTING -> colors.accent
                else -> colors.secondary
            }
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                if (status == ServerStatus.CHECKING) {
                    CircularProgressIndicator(Modifier.size(10.dp), color = statusColor, strokeWidth = 1.5.dp)
                } else {
                    Box(Modifier.size(6.dp).clip(CircleShape).background(statusColor))
                }
                Text(
                    text = if (status == ServerStatus.CHECKING) "Перевіряємо зв’язок" else status.label,
                    color = colors.secondary,
                    style = MaterialTheme.typography.bodySmall,
                    fontSize = 11.sp,
                    lineHeight = 14.sp,
                )
            }
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            DrawerQuickAction(
                label = "Обрати КПП",
                icon = Icons.Outlined.Place,
                enabled = canChooseCheckpoint,
                filled = true,
                busy = false,
                colors = colors,
                onClick = onChooseCheckpoint,
                modifier = Modifier.weight(1f),
            )
            DrawerQuickAction(
                label = if (refreshing) "Оновлюємо" else "Оновити дані",
                icon = Icons.Outlined.Refresh,
                enabled = canRefresh,
                filled = false,
                busy = refreshing,
                colors = colors,
                onClick = onRefresh,
                modifier = Modifier.weight(1f),
            )
        }
    }
}

@Composable
private fun DrawerQuickAction(
    label: String,
    icon: ImageVector,
    enabled: Boolean,
    filled: Boolean,
    busy: Boolean,
    colors: DrawerColors,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val shape = RoundedCornerShape(12.dp)
    val alpha = if (enabled || busy) 1f else 0.45f
    val foreground = (if (filled) colors.onAccent else colors.accent).copy(alpha = alpha)
    Row(
        modifier.heightIn(min = 44.dp).clip(shape)
            .background(if (filled) colors.accent.copy(alpha = alpha) else Color.Transparent)
            .border(1.dp, colors.accent.copy(alpha = alpha), shape)
            .clickable(enabled = enabled, role = Role.Button, onClick = hapticClick(onClick))
            .padding(horizontal = 8.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp, Alignment.CenterHorizontally),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (busy) {
            CircularProgressIndicator(Modifier.size(16.dp), color = foreground, strokeWidth = 2.dp)
        } else {
            Icon(icon, contentDescription = null, tint = foreground, modifier = Modifier.size(16.dp))
        }
        Text(label, color = foreground, style = MaterialTheme.typography.bodySmall,
            fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f, fill = false))
    }
}

@Composable
private fun DrawerSection(title: String, colors: DrawerColors, content: @Composable () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(title, color = colors.secondary, style = MaterialTheme.typography.labelSmall,
            modifier = Modifier.padding(start = 12.dp).semantics { heading() })
        content()
    }
}

@Composable
private fun DrawerGroup(colors: DrawerColors, content: @Composable () -> Unit) {
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(20.dp)).background(colors.group),
    ) { content() }
}

@Composable
private fun DrawerDivider(colors: DrawerColors) {
    HorizontalDivider(color = colors.divider, thickness = 0.5.dp)
}

@Composable
private fun DrawerThemeToggle(
    dark: Boolean,
    enabled: Boolean,
    colors: DrawerColors,
    onToggleTheme: () -> Unit,
) {
    val toggle = hapticClick(onToggleTheme)
    Row(
        Modifier.fillMaxWidth().heightIn(min = 48.dp)
            .toggleable(value = dark, enabled = enabled, role = Role.Switch, onValueChange = { toggle() })
            .padding(horizontal = 14.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Icon(if (dark) Icons.Outlined.DarkMode else Icons.Outlined.LightMode,
            contentDescription = null, tint = colors.secondary, modifier = Modifier.size(22.dp))
        Text("Темна тема", color = colors.text, style = MaterialTheme.typography.titleMedium,
            modifier = Modifier.weight(1f))
        Switch(
            checked = dark,
            onCheckedChange = null,
            enabled = enabled,
            colors = SwitchDefaults.colors(
                checkedThumbColor = colors.onAccent,
                checkedTrackColor = colors.accent,
                checkedBorderColor = colors.accent,
                uncheckedThumbColor = colors.secondary,
                uncheckedTrackColor = colors.group,
                uncheckedBorderColor = colors.divider,
            ),
        )
    }
}

@Composable
private fun DrawerRow(
    destination: FullTestDestination,
    title: String,
    icon: ImageVector,
    selectedDestination: FullTestDestination?,
    enabled: Boolean,
    colors: DrawerColors,
    onClose: () -> Unit,
    onSelect: (FullTestDestination) -> Unit,
    badgeCount: Int? = null,
) {
    val isSelected = destination == selectedDestination
    val foreground = if (isSelected) colors.onAccent else colors.text
    Row(
        Modifier.fillMaxWidth().heightIn(min = 48.dp)
            .background(if (isSelected) colors.accent else Color.Transparent)
            .semantics {
                selected = isSelected
                if (badgeCount != null) stateDescription = "Пороги та ETA: $badgeCount"
            }
            .clickable(enabled = enabled, role = Role.Button, onClick = hapticClick {
                onClose()
                onSelect(destination)
            })
            .padding(horizontal = 14.dp, vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Icon(icon, null, tint = if (isSelected) colors.onAccent else colors.secondary,
            modifier = Modifier.size(22.dp))
        Text(title, color = foreground, style = MaterialTheme.typography.titleMedium,
            modifier = Modifier.weight(1f))
        if (badgeCount != null) {
            val badgeColor = if (isSelected) colors.onAccent else colors.accent
            Text(
                text = badgeCount.toString(),
                color = badgeColor,
                style = MaterialTheme.typography.labelLarge,
                modifier = Modifier.clearAndSetSemantics { }.clip(RoundedCornerShape(8.dp))
                    .background(badgeColor.copy(alpha = 0.12f)).widthIn(min = 24.dp)
                    .padding(horizontal = 7.dp, vertical = 3.dp),
                textAlign = TextAlign.Center,
            )
        }
        Icon(Icons.Filled.ChevronRight, null,
            tint = if (isSelected) colors.onAccent else colors.secondary,
            modifier = Modifier.size(18.dp))
    }
}

@Composable
internal fun FullTestMenuButton(onClick: () -> Unit, modifier: Modifier = Modifier) {
    val colors = drawerColors()
    IconButton(
        onClick = hapticClick(onClick),
        modifier = modifier.size(60.dp).clip(CircleShape).background(colors.group),
    ) {
        Icon(Icons.Filled.Menu, contentDescription = "Меню", tint = colors.accent, modifier = Modifier.size(28.dp))
    }
}
