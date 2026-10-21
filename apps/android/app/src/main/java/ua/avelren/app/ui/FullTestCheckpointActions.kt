package ua.avelren.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.BarChart
import androidx.compose.material.icons.filled.HourglassEmpty
import androidx.compose.material.icons.outlined.Insights
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import ua.avelren.app.ui.theme.AppAccent
import ua.avelren.app.ui.theme.AppInk
import ua.avelren.app.ui.theme.avelren
import ua.avelren.app.ui.theme.hapticClick

/** Швидкі дії для КПП на головному екрані; створення підписки підтверджується в наявному діалозі. */
@Composable
internal fun FullTestCheckpointActions(
    canChangeMonitors: Boolean,
    onThreshold: () -> Unit,
    onEta: () -> Unit,
    onForecast: () -> Unit,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Text(
            text = "Для цього КПП",
            color = MaterialTheme.avelren.ink2,
            style = MaterialTheme.typography.bodySmall,
            modifier = Modifier.padding(horizontal = 2.dp),
        )
        Row(
            modifier = Modifier.fillMaxWidth().height(IntrinsicSize.Min),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            FullTestCheckpointAction(
                label = "Поріг авто",
                description = "Задати поріг авто для цього КПП",
                icon = Icons.Filled.BarChart,
                enabled = canChangeMonitors,
                onClick = onThreshold,
                modifier = Modifier.weight(1f),
            )
            FullTestCheckpointAction(
                label = "Час в’їзду",
                description = "Задати бажаний час в’їзду для цього КПП",
                icon = Icons.Filled.HourglassEmpty,
                enabled = canChangeMonitors,
                onClick = onEta,
                modifier = Modifier.weight(1f),
            )
            FullTestCheckpointAction(
                label = "Прогноз",
                description = "Відкрити прогноз черги для цього КПП",
                icon = Icons.Outlined.Insights,
                enabled = true,
                onClick = onForecast,
                modifier = Modifier.weight(1f),
            )
        }
    }
}

@Composable
private fun FullTestCheckpointAction(
    label: String,
    description: String,
    icon: ImageVector,
    enabled: Boolean,
    onClick: () -> Unit,
    modifier: Modifier,
) {
    val shape = RoundedCornerShape(16.dp)
    val foreground = if (enabled) AppInk else MaterialTheme.avelren.ink2
    Column(
        modifier = modifier.fillMaxHeight().heightIn(min = 76.dp)
            .clip(shape)
            .background(MaterialTheme.colorScheme.surfaceVariant)
            .border(1.dp, MaterialTheme.avelren.line, shape)
            .semantics(mergeDescendants = true) { contentDescription = description }
            .clickable(enabled = enabled, role = Role.Button, onClick = hapticClick(onClick))
            .padding(horizontal = 8.dp, vertical = 12.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(6.dp, Alignment.CenterVertically),
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = if (enabled) AppAccent else MaterialTheme.avelren.ink2,
            modifier = Modifier.size(24.dp),
        )
        Text(
            text = label,
            color = foreground,
            style = MaterialTheme.typography.bodySmall.copy(fontWeight = FontWeight.Bold),
            textAlign = TextAlign.Center,
        )
    }
}
