package ua.avelren.app.data

import java.time.LocalDate
import java.time.Instant
import java.time.Duration
import java.time.OffsetDateTime
import java.time.ZoneId

/** Presentation helpers for the daily forecast; API timestamps are absolute instants. */
object ForecastPresentation {
    private val kyiv = ZoneId.of("Europe/Kyiv")

    /** Явно порожній count_points не підміняється старими wait-фільтрованими точками. */
    fun displayPoints(forecast: Api.Forecast): List<Api.CountForecastPoint> =
        forecast.count_points ?: forecast.points.map {
            Api.CountForecastPoint(it.time, it.vehicles_low, it.vehicles_expected, it.vehicles_high)
        }

    fun next24CountHours(points: List<Api.CountForecastPoint>, now: Instant): List<Api.CountForecastPoint> =
        points.mapNotNull { point ->
            runCatching { OffsetDateTime.parse(point.time).toInstant() }.getOrNull()
                ?.takeIf { it > now && it <= now.plus(Duration.ofHours(24)) }
                ?.let { it to point }
        }.sortedBy { it.first }.distinctBy { it.first }.map { it.second }

    fun countPeak(points: List<Api.CountForecastPoint>): Api.CountForecastPoint? =
        points.maxByOrNull { it.vehicles_expected }

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
