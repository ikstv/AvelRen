package ua.avelren.app.data

import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.ZoneId

/** Presentation helpers for the daily forecast; API timestamps are absolute instants. */
object ForecastPresentation {
    private val kyiv = ZoneId.of("Europe/Kyiv")

    fun forKyivDate(points: List<Api.ForecastPoint>, date: LocalDate): List<Api.ForecastPoint> =
        points.filter { point ->
            runCatching {
                OffsetDateTime.parse(point.time).atZoneSameInstant(kyiv).toLocalDate() == date
            }.getOrDefault(false)
        }

    fun peak(points: List<Api.ForecastPoint>): Api.ForecastPoint? =
        points.maxByOrNull { it.vehicles_expected }
}
