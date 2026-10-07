package ua.avelren.app.ui

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.drawscope.clipRect
import androidx.compose.ui.semantics.ProgressBarRangeInfo
import androidx.compose.ui.semantics.progressBarRangeInfo
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import java.time.Instant
import java.util.Locale
import kotlinx.coroutines.launch
import ua.avelren.app.ui.theme.SignGo
import ua.avelren.app.ui.theme.SignWarn
import ua.avelren.app.ui.theme.SignClosed

@OptIn(ExperimentalLayoutApi::class)
@Composable
internal fun ServerStatusContent(server: AdminServerClient, modifier: Modifier = Modifier) {
    val loader = remember(server) { ServerCpuLoader(server::serverCpuStatus) }
    val scope = rememberCoroutineScope()
    // Exactly one initial request per opened tab. No HTTP polling, focus refresh or retry.
    LaunchedEffect(loader) { loader.refresh() }
    // Hide expired values even if the user leaves this screen untouched; no HTTP polling.
    LaunchedEffect(loader, loader.status) { loader.expireSnapshot() }
    val presentation = serverStatusPresentation(loader.status, Instant.now())
    Column(modifier.verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 24.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Text("Стан сервера", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        FlowRow(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp)) {
            TextButton(onClick = { scope.launch { loader.refresh() } }, enabled = !loader.busy,
                modifier = Modifier.heightIn(min = 48.dp)) { Text("Оновити") }
            Text("Виміряно: ${presentation.measuredAt ?: "—"}",
                modifier = Modifier.padding(vertical = 14.dp),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("CPU", Modifier.weight(1f), style = MaterialTheme.typography.titleMedium)
            Text(presentation.percent?.let { String.format(Locale.ROOT, "%.1f%%", it) } ?: "—",
                style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.Bold)
        }
        CpuBar(presentation.percent)
        when {
            loader.busy -> Text("Оновлюємо дані…", style = MaterialTheme.typography.bodySmall)
            loader.error != null -> Text(loader.error!!, color = MaterialTheme.colorScheme.error)
            presentation.percent == null -> Text("Немає свіжих даних CPU.",
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            else -> Text("Знімок навантаження всього сервера за 1 секунду.",
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun CpuBar(percent: Double?) {
    val fraction = (percent?.div(100.0) ?: 0.0).toFloat()
    val track = MaterialTheme.colorScheme.surfaceVariant
    Canvas(Modifier.fillMaxWidth().height(26.dp).semantics {
        if (percent != null) progressBarRangeInfo = ProgressBarRangeInfo(fraction, 0f..1f)
    }) {
        val y = 7.dp.toPx()
        val height = 12.dp.toPx()
        drawRoundRect(track, Offset(0f, y), Size(size.width, height), CornerRadius(height / 2))
        if (fraction > 0f) {
            val brush = Brush.horizontalGradient(listOf(SignGo, SignWarn, SignClosed), endX = size.width)
            clipRect(right = size.width * fraction) {
                // Static translucent halo: no blur bitmap, animation or repeated sampling.
                drawRoundRect(brush, Offset(0f, y - 3.dp.toPx()), Size(size.width, height + 6.dp.toPx()),
                    CornerRadius(height), alpha = 0.14f)
                drawRoundRect(brush, Offset(0f, y), Size(size.width, height), CornerRadius(height / 2))
            }
        }
    }
}
