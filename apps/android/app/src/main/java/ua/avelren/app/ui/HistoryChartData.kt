package ua.avelren.app.ui

import ua.avelren.app.data.Api
import java.time.Duration
import java.time.Instant

internal data class HistoryChartSample(val position: Float, val vehicles: Int, val time: Instant)

internal fun historyChartSegments(points: List<Api.HistoryPoint>, end: Instant): List<List<HistoryChartSample>> {
    val start = end.minusSeconds(24 * 60 * 60)
    val samples = points.mapNotNull { point ->
        val time = runCatching { Instant.parse(point.time) }.getOrNull() ?: return@mapNotNull null
        if (time < start || time > end) return@mapNotNull null
        HistoryChartSample(Duration.between(start, time).toMillis() / 86400000f, point.vehicles_in_queue, time)
    }.sortedBy { it.time }
    val segments = mutableListOf<MutableList<HistoryChartSample>>()
    for (sample in samples) {
        if (segments.isEmpty() || Duration.between(segments.last().last().time, sample.time).seconds > 180) segments.add(mutableListOf())
        segments.last().add(sample)
    }
    return segments
}
