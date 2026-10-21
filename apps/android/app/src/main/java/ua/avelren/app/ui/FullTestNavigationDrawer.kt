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
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.rememberScrollState
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
import androidx.compose.material.icons.outlined.Notifications
import androidx.compose.material.icons.outlined.Schedule
import androidx.compose.material.icons.outlined.Shield
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
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
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.isTraversalGroup
import androidx.compose.ui.semantics.paneTitle
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import androidx.compose.ui.window.DialogWindowProvider
import androidx.core.view.WindowCompat
import ua.avelren.app.BuildConfig
import ua.avelren.app.R
import ua.avelren.app.ui.theme.LocalThemeChoice
import ua.avelren.app.ui.theme.ThemeChoice
import ua.avelren.app.ui.theme.hapticClick

internal enum class FullTestDestination {
    HOME, MONITOR, FORECAST, NOTIFICATIONS, THEME, ABOUT, PRIVACY, DEVELOPER,
}

private data class DrawerColors(
    val panel: Color,
    val group: Color,
    val text: Color,
    val secondary: Color,
    val divider: Color,
)

@Composable
private fun drawerColors(): DrawerColors = if (LocalThemeChoice.current == ThemeChoice.LIGHT) {
    DrawerColors(
        panel = Color(0xFFF5F6F8),
        group = Color.White,
        text = Color(0xFF191D23),
        secondary = Color(0xFF59616C),
        divider = Color(0xFFE8EAEE),
    )
} else {
    DrawerColors(
        panel = Color(0xFF0B0D0F),
        group = Color(0xFF15181B),
        text = Color(0xFFF0F1F3),
        secondary = Color(0xFFA4ABB4),
        divider = Color(0xFF22262B),
    )
}

/** Тестова навігація. Окреме modal-вікно ізолює фокус і Back від вмісту під ним. */
@Composable
internal fun FullTestNavigationDrawer(
    open: Boolean,
    selected: FullTestDestination?,
    onClose: () -> Unit,
    onSelect: (FullTestDestination) -> Unit,
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
            usePlatformDefaultWidth = false,
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
                Column(
                    Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState()),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    DrawerGroup(colors) {
                        DrawerRow(FullTestDestination.HOME, "Головна", "Черга на обраному КПП",
                            Icons.Outlined.Home, selected, open, colors, onClose, onSelect)
                        DrawerDivider(colors)
                        DrawerRow(FullTestDestination.MONITOR, "Моніторинг", "Пороги та час в’їзду",
                            Icons.Outlined.Schedule, selected, open, colors, onClose, onSelect)
                        DrawerDivider(colors)
                        DrawerRow(FullTestDestination.FORECAST, "Прогноз черги", "Прогноз, зростання та голос",
                            Icons.Outlined.Insights, selected, open, colors, onClose, onSelect)
                    }
                    DrawerGroup(colors) {
                        DrawerRow(FullTestDestination.NOTIFICATIONS, "Сповіщення", "Звук і дозволи",
                            Icons.Outlined.Notifications, selected, open, colors, onClose, onSelect)
                        DrawerDivider(colors)
                        DrawerRow(FullTestDestination.THEME, "Тема", "Темна або світла",
                            Icons.Outlined.DarkMode, selected, open, colors, onClose, onSelect)
                    }
                    DrawerGroup(colors) {
                        DrawerRow(FullTestDestination.ABOUT, "Про застосунок", null,
                            Icons.Outlined.Info, selected, open, colors, onClose, onSelect)
                        DrawerDivider(colors)
                        DrawerRow(FullTestDestination.PRIVACY, "Політика конфіденційності", null,
                            Icons.Outlined.Shield, selected, open, colors, onClose, onSelect)
                        DrawerDivider(colors)
                        DrawerRow(FullTestDestination.DEVELOPER, "Для розробника", null,
                            Icons.Outlined.Code, selected, open, colors, onClose, onSelect)
                    }
                    Spacer(Modifier.height(4.dp))
                }
                Text(
                    text = "Версія ${BuildConfig.VERSION_NAME} · FullTest",
                    color = colors.secondary,
                    fontSize = 12.sp,
                    fontFamily = FontFamily.SansSerif,
                    modifier = Modifier.padding(horizontal = 12.dp, vertical = 16.dp),
                )
            }
        }
    }
}

@Composable
private fun DrawerHeader(colors: DrawerColors, onClose: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().padding(start = 8.dp, end = 2.dp, top = 12.dp, bottom = 20.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Image(
            painter = painterResource(R.drawable.ic_launcher_foreground),
            contentDescription = null,
            modifier = Modifier.size(48.dp).clip(RoundedCornerShape(14.dp))
                .background(Color(0xFF15181B)),
        )
        Column(Modifier.weight(1f)) {
            Text("AvelRen", color = colors.text, fontSize = 24.sp,
                fontWeight = FontWeight.Bold, fontFamily = FontFamily.SansSerif)
            Text("Черги на кордоні", color = colors.secondary, fontSize = 12.sp,
                fontFamily = FontFamily.SansSerif)
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
private fun DrawerGroup(colors: DrawerColors, content: @Composable () -> Unit) {
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(24.dp)).background(colors.group),
    ) { content() }
}

@Composable
private fun DrawerDivider(colors: DrawerColors) {
    HorizontalDivider(color = colors.divider, thickness = 0.5.dp)
}

@Composable
private fun DrawerRow(
    destination: FullTestDestination,
    title: String,
    subtitle: String?,
    icon: ImageVector,
    selectedDestination: FullTestDestination?,
    enabled: Boolean,
    colors: DrawerColors,
    onClose: () -> Unit,
    onSelect: (FullTestDestination) -> Unit,
) {
    val isSelected = destination == selectedDestination
    val foreground = if (isSelected) Color.White else colors.text
    Row(
        Modifier.fillMaxWidth().heightIn(min = if (subtitle == null) 60.dp else 72.dp)
            .background(if (isSelected) Color(0xFF075BB7) else Color.Transparent)
            .semantics { selected = isSelected }
            .clickable(enabled = enabled, role = Role.Button, onClick = hapticClick {
                onClose()
                onSelect(destination)
            })
            .padding(horizontal = 16.dp, vertical = 14.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(14.dp),
    ) {
        Icon(icon, null, tint = if (isSelected) Color.White else colors.secondary,
            modifier = Modifier.size(24.dp))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
            Text(title, color = foreground, fontSize = 17.sp, fontWeight = FontWeight.Medium,
                fontFamily = FontFamily.SansSerif, lineHeight = 22.sp)
            if (subtitle != null) {
                Text(subtitle, color = if (isSelected) Color(0xFFDBEAFE) else colors.secondary,
                    fontSize = 13.sp, fontFamily = FontFamily.SansSerif, lineHeight = 18.sp)
            }
        }
        Icon(Icons.Filled.ChevronRight, null,
            tint = if (isSelected) Color.White else colors.secondary,
            modifier = Modifier.size(20.dp))
    }
}

@Composable
internal fun FullTestMenuButton(onClick: () -> Unit, modifier: Modifier = Modifier) {
    val colors = drawerColors()
    IconButton(
        onClick = hapticClick(onClick),
        modifier = modifier.size(60.dp).clip(CircleShape).background(colors.group),
    ) {
        Icon(Icons.Filled.Menu, contentDescription = "Меню", tint = colors.text, modifier = Modifier.size(28.dp))
    }
}
