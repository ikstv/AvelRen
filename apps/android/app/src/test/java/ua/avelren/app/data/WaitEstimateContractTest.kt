package ua.avelren.app.data

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import org.junit.Assert.*
import org.junit.Test

class WaitEstimateContractTest {
    private val json = Json { ignoreUnknownKeys = true }
    private val old = """{"checkpoint_id":17,"title":"Тест","vehicles_in_queue":80,"wait_time_seconds":0,"is_paused":false,"entry_eta":"2026-10-02T12:00:00Z"}"""

    @Serializable
    private data class FrozenWorkload(val checkpoint_id: Int, val title: String, val vehicles_in_queue: Int, val wait_time_seconds: Int, val is_paused: Boolean, val entry_eta: String? = null)

    @Test fun `new nullable object and old numeric fields decode in both clients`() {
        val legacy = json.decodeFromString<Api.Workload>(old)
        assertNull(legacy.wait_estimate)
        val fresh = old.dropLast(1) + """, "wait_estimate":{"status":"missing","seconds":null,"entry_eta":null}}"""
        val decoded = json.decodeFromString<Api.Workload>(fresh)
        assertEquals("missing", decoded.wait_estimate?.status)
        assertNull(decoded.wait_estimate?.seconds)
        assertEquals(80, json.decodeFromString<FrozenWorkload>(fresh).vehicles_in_queue)
        assertNull(WaitPresentation.entryEta(decoded))
        assertEquals(legacy.entry_eta, WaitPresentation.entryEta(legacy))
    }

    @Test fun `reported zero survives JSON and nullable historical fields decode`() {
        val fresh = old.dropLast(1) + """, "wait_estimate":{"status":"reported","seconds":0,"entry_eta":"2026-10-02T12:00:00Z"}}"""
        assertEquals(0, json.decodeFromString<Api.Workload>(fresh).wait_estimate?.seconds)
        val history = json.decodeFromString<Api.History>("""{"resolution":"hourly","points":[],"count_hours":[{"time":"2026-10-02T12:00:00Z","avg_vehicles":80.0,"samples":60}],"wait_hours":[]}""")
        assertEquals(60, history.count_hours?.single()?.samples)
        assertTrue(history.wait_hours!!.isEmpty())
        val raw = json.decodeFromString<Api.HistoryPoint>("""{"time":"2026-10-02T12:00:00Z","vehicles_in_queue":80,"wait_time_status":"missing","wait_estimate_seconds":null}""")
        assertEquals("missing", raw.wait_time_status)
        assertNull(raw.wait_estimate_seconds)
    }

    @Test fun `explicit empty count points never revives legacy points`() {
        val legacy = Api.ForecastPoint("2026-10-02T12:00:00Z", 3600, 3600, 3600, vehicles_expected = 80)
        val fallback = Api.Forecast(17, "ready", 12.0, 12, points = listOf(legacy))
        assertEquals(80, ForecastPresentation.displayPoints(fallback).single().vehicles_expected)
        assertNull(ForecastPresentation.displayPoints(fallback).single().vehicles_low)
        assertEquals(0, ForecastPresentation.displayPoints(fallback).single().calibration_samples)
        assertTrue(ForecastPresentation.displayPoints(fallback.copy(count_points = emptyList())).isEmpty())
        val fresh = json.decodeFromString<Api.Forecast>("""{"checkpoint_id":17,"status":"ready","weeks_collected":12.0,"weeks_needed":12,"count_points":[{"time":"2026-10-02T12:00:00Z","vehicles_low":70,"vehicles_expected":80,"vehicles_high":90,"calibration_samples":8,"wait_estimate":null}]}""")
        assertNull(ForecastPresentation.displayPoints(fresh).single().wait_estimate)
        assertEquals(8, ForecastPresentation.displayPoints(fresh).single().calibration_samples)
    }
}
