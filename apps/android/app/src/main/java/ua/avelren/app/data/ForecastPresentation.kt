package ua.avelren.app.data

import java.time.LocalDate
import java.time.Instant
import java.time.Duration
import java.time.OffsetDateTime
import java.time.ZoneId

/** Presentation helpers for the daily forecast; API timestamps are absolute instants. */
object ForecastPresentation {
    private val kyiv = ZoneId.of("Europe/Kyiv")

    /** Rolling 24 elapsed hours, including tomorrow and Kyiv DST transitions. */
    fun next24Hours(points: List<Api.ForecastPoint>, now: Instant): List<Api.ForecastPoint> =
        points.mapNotNull { point ->
            runCatching { OffsetDateTime.parse(point.time).toInstant() }.getOrNull()
                ?.takeIf { it > now && it <= now.plus(Duration.ofHours(24)) }
                ?.let { it to point }
        }.sortedBy { it.first }.distinctBy { it.first }.map { it.second }

    fun forKyivDate(points: List<Api.ForecastPoint>, date: LocalDate): List<Api.ForecastPoint> =
        points.filter { point ->
            runCatching {
                OffsetDateTime.parse(point.time).atZoneSameInstant(kyiv).toLocalDate() == date
            }.getOrDefault(false)
        }

    fun peak(points: List<Api.ForecastPoint>): Api.ForecastPoint? =
        points.maxByOrNull { it.vehicles_expected }
}
