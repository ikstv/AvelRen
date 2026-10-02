package ua.avelren.app.data

import kotlinx.serialization.json.Json
import org.junit.Assert.*
import org.junit.Test

class SurgeContractTest {
    private val json = Json { ignoreUnknownKeys = true }
    @Test fun `unknown fields and missing optional data remain compatible`() {
        val status = json.decodeFromString<SurgeStatus>(
            """{"checkpoint_id":17,"status":"unavailable","forecast_supported":true,"future":123}""")
        assertNull(status.window_start)
        assertNull(status.growth_5m)
        assertEquals("unavailable", status.status)
    }
    @Test fun `own subscription keeps forecast and fact separate`() {
        val sub = json.decodeFromString<SurgeSubscription>(
            """{"checkpoint_id":17,"title":"Чоп","forecast_enabled":true,"fact_enabled":false,"alerts":[]}""")
        assertTrue(sub.forecast_enabled)
        assertFalse(sub.fact_enabled)
    }
    @Test fun `old active alerts omit surge lists safely`() {
        val old = json.decodeFromString<Api.ActiveAlerts>("""{"threshold":[1],"eta":[]}""")
        assertTrue(old.surge_forecast.isEmpty())
        assertTrue(old.surge_started.isEmpty())
    }
}
