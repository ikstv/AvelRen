package ua.avelren.app.ui

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.outlined.Notifications
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import ua.avelren.app.ui.theme.AppAccent
import ua.avelren.app.ui.theme.AppInk
import ua.avelren.app.ui.theme.AppOnAccent
import ua.avelren.app.ui.theme.Overpass
import ua.avelren.app.ui.theme.avelren
import ua.avelren.app.ui.theme.hapticClick

/** Нижня навігація експериментальної FullTest-збірки; системні відступи задає батьківський екран. */
@Composable
internal fun FullTestBottomBar(
    activeTab: String,
    monitorCount: Int?,
    onOpenMenu: () -> Unit,
    onHome: () -> Unit,
    onMonitoring: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val shape = RoundedCornerShape(24.dp)
    Row(
        modifier = modifier.fillMaxWidth()
            .clip(shape)
            .background(MaterialTheme.colorScheme.surfaceVariant)
            .border(1.dp, MaterialTheme.avelren.line, shape)
            .padding(4.dp),
        horizontalArrangement = Arrangement.spacedBy(4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        FullTestDockAction(
            label = "Меню",
            icon = Icons.Filled.Menu,
            active = activeTab == "settings",
            role = Role.Button,
            onClick = onOpenMenu,
            modifier = Modifier.weight(1f),
        )
        FullTestDockAction(
            label = "Головна",
            icon = Icons.Outlined.Home,
            active = activeTab == "home",
            onClick = onHome,
            modifier = Modifier.weight(1f),
        )
        FullTestDockAction(
            label = "Моніторинг",
            icon = Icons.Outlined.Notifications,
            active = activeTab == "monitor",
            count = monitorCount,
            onClick = onMonitoring,
            modifier = Modifier.weight(1f),
        )
    }
}

@Composable
private fun FullTestDockAction(
    label: String,
    icon: ImageVector,
    active: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    role: Role = Role.Tab,
    count: Int? = null,
) {
    val background by animateColorAsState(
        targetValue = if (active) AppAccent else Color.Transparent,
        animationSpec = tween(180),
        label = "Dock selection background",
    )
    val foreground by animateColorAsState(
        targetValue = if (active) AppOnAccent else AppInk,
        animationSpec = tween(180),
        label = "Dock selection foreground",
    )
    Column(
        modifier = modifier.heightIn(min = 56.dp)
            .clip(RoundedCornerShape(20.dp))
            .background(background)
            .semantics(mergeDescendants = true) {
                selected = active
                if (count != null && count >= 0) stateDescription = "Пороги та ETA: $count"
            }
            .clickable(role = role, onClick = hapticClick(onClick))
            .padding(horizontal = 4.dp, vertical = 6.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(3.dp, Alignment.CenterVertically),
    ) {
        Box(Modifier.width(64.dp).heightIn(min = 24.dp), contentAlignment = Alignment.Center) {
            Icon(icon, contentDescription = null, modifier = Modifier.size(24.dp), tint = foreground)
            if (count != null && count > 0) {
                Box(
                    modifier = Modifier.align(Alignment.TopEnd)
                        .widthIn(min = 16.dp)
                        .clip(RoundedCornerShape(8.dp))
                        .background(if (active) AppOnAccent else AppAccent)
                        .clearAndSetSemantics { }
                        .padding(horizontal = 4.dp, vertical = 1.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    Text(
                        text = if (count > 99) "99+" else count.toString(),
                        color = if (active) AppAccent else AppOnAccent,
                        fontFamily = Overpass,
                        fontWeight = FontWeight.Bold,
                        fontSize = 10.sp,
                        lineHeight = 12.sp,
                        maxLines = 1,
                    )
                }
            }
        }
        Text(
            text = label,
            color = foreground,
            style = MaterialTheme.typography.bodySmall.copy(fontWeight = FontWeight.Bold),
            textAlign = TextAlign.Center,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
    }
}
