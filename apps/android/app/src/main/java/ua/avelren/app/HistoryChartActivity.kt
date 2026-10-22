package ua.avelren.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.CancellationException
import ua.avelren.app.data.Api
import ua.avelren.app.ui.HistoryChartSample
import ua.avelren.app.ui.historyChartSegments
import ua.avelren.app.ui.historyChartTimeLabels
import ua.avelren.app.ui.colorForRate
import ua.avelren.app.ui.theme.AvelRenTheme
import java.time.Instant

class HistoryChartActivity : ComponentActivity() {
    companion object {
        const val CHECKPOINT_ID = "checkpoint_id"
        const val CHECKPOINT_TITLE = "checkpoint_title"
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val id = intent.getIntExtra(CHECKPOINT_ID, -1)
        if (id < 0) { finish(); return }
        val title = intent.getStringExtra(CHECKPOINT_TITLE).orEmpty()
        setContent { AvelRenTheme { Surface(color = MaterialTheme.colorScheme.background, contentColor = MaterialTheme.colorScheme.onBackground) { HistoryScreen(id, title, onBack = { finish() }) } } }
    }
}

@Composable
private fun HistoryScreen(id: Int, title: String, onBack: () -> Unit) {
    var retry by remember { mutableIntStateOf(0) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf(false) }
    var segments by remember { mutableStateOf<List<List<HistoryChartSample>>>(emptyList()) }
    var chartEnd by remember { mutableStateOf(Instant.now()) }
    LaunchedEffect(id, retry) {
        loading = true; error = false
        try {
            val history = Api.history(id, 24)
            chartEnd = Instant.now()
            segments = historyChartSegments(history.points, chartEnd)
        } catch (e: CancellationException) { throw e }
        catch (_: Exception) { error = true }
        finally { loading = false }
    }
    Column(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)
        .windowInsetsPadding(WindowInsets.safeDrawing).padding(horizontal = 16.dp, vertical = 6.dp)) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            TextButton(onClick = onBack) { Text("‹ Назад") }
            Spacer(Modifier.width(8.dp))
            Column {
                Text(title, style = MaterialTheme.typography.titleMedium, maxLines = 1)
                val dates = remember(chartEnd) {
                    val format = java.time.format.DateTimeFormatter.ofPattern("dd.MM").withZone(java.time.ZoneId.of("Europe/Kyiv"))
                    "${format.format(chartEnd.minusSeconds(86400))}–${format.format(chartEnd)}"
                }
                Text("Динаміка черги · $dates · час Києва", style = MaterialTheme.typography.bodySmall)
            }
        }
        when {
            loading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
            error -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text("Не вдалося завантажити історію")
                    TextButton(onClick = { retry++ }) { Text("Спробувати ще раз") }
                }
            }
            segments.isEmpty() -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { Text("Немає даних за останні 24 години") }
            else -> HistoryGraph(segments, chartEnd, Modifier.weight(1f))
        }
    }
}

@Composable
private fun HistoryGraph(segments: List<List<HistoryChartSample>>, end: Instant, modifier: Modifier = Modifier) {
    val samples = segments.flatten()
    val lowest = (samples.minOfOrNull { it.vehicles } ?: 0).coerceAtLeast(0)
    val highest = (samples.maxOfOrNull { it.vehicles } ?: 0).coerceAtLeast(lowest)
    val padding = ((highest - lowest) / 10).coerceAtLeast(1)
    val minValue = (lowest - padding).coerceAtLeast(0)
    val maxValue = (highest + padding).coerceAtLeast(minValue + 1)
    val grid = MaterialTheme.colorScheme.onSurface.copy(alpha = .22f)
    val axisColor = MaterialTheme.colorScheme.onSurfaceVariant
    Column(modifier.fillMaxWidth()) {
        Text("Авто", style = MaterialTheme.typography.labelSmall)
        Spacer(Modifier.height(4.dp))
        Row(Modifier.fillMaxWidth().weight(1f)) {
            Column(Modifier.width(52.dp).fillMaxHeight().padding(end = 6.dp),
                verticalArrangement = Arrangement.SpaceBetween) {
                for (i in 0..4) {
                    val label = maxValue - (maxValue - minValue) * i / 4
                    Text("$label", fontSize = 11.sp, color = axisColor, maxLines = 1)
                }
            }
            Canvas(Modifier.weight(1f).fillMaxHeight().padding(vertical = 7.dp)) {
                for (i in 0..4) {
                    val y = size.height * i / 4f
                    drawLine(grid, Offset(0f, y), Offset(size.width, y), strokeWidth = 1.dp.toPx())
                }
                val dash = PathEffect.dashPathEffect(floatArrayOf(5.dp.toPx(), 4.dp.toPx()))
                for (i in 0..8) {
                    val x = size.width * i / 8f
                    drawLine(grid, Offset(x, 0f), Offset(x, size.height), strokeWidth = 1.dp.toPx(), pathEffect = dash)
                }
                fun point(sample: HistoryChartSample): Offset = Offset(sample.position * size.width,
                    size.height * (1f - (sample.vehicles.coerceAtLeast(0) - minValue).toFloat() / (maxValue - minValue)))
                segments.forEach { segment ->
                    if (segment.size == 1) {
                        drawCircle(colorForRate(0), radius = 3.dp.toPx(), center = point(segment.first()))
                    } else {
                        for (i in 1 until segment.size) {
                            val previous = segment[i - 1]
                            val current = segment[i]
                            val start = point(previous)
                            val end = point(current)
                            val color = colorForRate(current.vehicles - previous.vehicles)
                            val fill = Path().apply {
                                moveTo(start.x, start.y); lineTo(end.x, end.y)
                                lineTo(end.x, size.height); lineTo(start.x, size.height); close()
                            }
                            drawPath(fill, Brush.verticalGradient(
                                0f to color.copy(alpha = .38f), 1f to Color.Transparent,
                                startY = minOf(start.y, end.y), endY = size.height,
                            ))
                            drawLine(color, start, end, strokeWidth = 2.dp.toPx(), cap = StrokeCap.Round)
                        }
                    }
                }
            }
        }
        BoxWithConstraints(Modifier.fillMaxWidth().padding(start = 52.dp, top = 4.dp).height(20.dp)) {
            val labelWidth = 42.dp
            historyChartTimeLabels(end).forEachIndexed { index, label ->
                val center = maxWidth * (index / 8f)
                val start = (center - labelWidth / 2).coerceIn(0.dp, (maxWidth - labelWidth).coerceAtLeast(0.dp))
                Text(label, modifier = Modifier.offset(x = start).width(labelWidth),
                    textAlign = TextAlign.Center, fontSize = 11.sp, color = axisColor, maxLines = 1)
            }
        }
    }
}
