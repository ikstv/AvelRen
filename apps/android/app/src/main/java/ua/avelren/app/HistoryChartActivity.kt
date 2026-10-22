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
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.CancellationException
import ua.avelren.app.data.Api
import ua.avelren.app.ui.HistoryChartSample
import ua.avelren.app.ui.historyChartSegments
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
    LaunchedEffect(id, retry) {
        loading = true; error = false
        try {
            val history = Api.history(id, 24)
            segments = historyChartSegments(history.points, Instant.now())
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
                Text("Динаміка черги · останні 24 години", style = MaterialTheme.typography.bodySmall)
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
            else -> HistoryGraph(segments, Modifier.weight(1f))
        }
    }
}

@Composable
private fun HistoryGraph(segments: List<List<HistoryChartSample>>, modifier: Modifier = Modifier) {
    val samples = segments.flatten()
    val lowest = (samples.minOfOrNull { it.vehicles } ?: 0).coerceAtLeast(0)
    val highest = (samples.maxOfOrNull { it.vehicles } ?: 0).coerceAtLeast(lowest)
    val padding = ((highest - lowest) / 10).coerceAtLeast(1)
    val minValue = (lowest - padding).coerceAtLeast(0)
    val maxValue = (highest + padding).coerceAtLeast(minValue + 1)
    val line = MaterialTheme.colorScheme.primary
    val grid = MaterialTheme.colorScheme.onSurface.copy(alpha = .16f)
    Column(modifier.fillMaxWidth()) {
        Text("Авто · $minValue–$maxValue", style = MaterialTheme.typography.labelSmall)
        Spacer(Modifier.height(4.dp))
        Canvas(Modifier.fillMaxWidth().weight(1f)) {
            for (i in 0..4) {
                val y = size.height * i / 4f
                drawLine(grid, Offset(0f, y), Offset(size.width, y), strokeWidth = 1.dp.toPx())
            }
            fun point(sample: HistoryChartSample): Offset = Offset(sample.position * size.width,
                size.height * (1f - (sample.vehicles.coerceAtLeast(0) - minValue).toFloat() / (maxValue - minValue)))
            segments.forEach { segment ->
                if (segment.size == 1) drawCircle(line, radius = 3.dp.toPx(), center = point(segment.first()))
                else {
                    val path = Path().apply {
                        val first = point(segment.first()); moveTo(first.x, first.y)
                        segment.drop(1).forEach { val p = point(it); lineTo(p.x, p.y) }
                    }
                    val fill = Path().apply {
                        val first = point(segment.first()); moveTo(first.x, size.height); lineTo(first.x, first.y)
                        segment.drop(1).forEach { val p = point(it); lineTo(p.x, p.y) }
                        lineTo(point(segment.last()).x, size.height); close()
                    }
                    drawPath(fill, Brush.verticalGradient(listOf(line.copy(alpha = .35f), Color.Transparent), endY = size.height))
                    drawPath(path, line, style = androidx.compose.ui.graphics.drawscope.Stroke(width = 2.dp.toPx(), cap = StrokeCap.Round))
                }
            }
        }
        Row(Modifier.fillMaxWidth().padding(top = 4.dp), horizontalArrangement = Arrangement.SpaceBetween) {
            listOf("−24 год", "−18 год", "−12 год", "−6 год", "Зараз").forEach {
                Text(it, fontSize = 11.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}
