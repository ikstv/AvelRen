package ua.avelren.app.data

import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Контракт десеріалізації `/admin/telemetry`. Новий Server Dashboard додав
 * опціональні поля (last_observation, runs_last_hour, load_5m, stale,
 * certificate.error, backups.last_run, alerts_pending, collecting_since,
 * snapshot_age_seconds). Тест страхує від сценарію:
 *
 * 1. Старий сервер (без нових полів) — новий APK має парситись без винятку.
 * 2. Новий сервер (з полями) — Android має їх прочитати правильно.
 *
 * Без цього тесту випадковий `required` (не-nullable) у data class зламав би
 * телеметрію на всіх пристроях до наступного deploy сервера.
 */
class TelemetryDeserializationTest {

    private val json = Json { ignoreUnknownKeys = true }

    @Test fun `парсинг мінімального payload зі старого сервера`() {
        // Формат: рівно те, що віддавав сервер ДО PR-A (без нових полів).
        val payload = """
            {
              "system": {
                "uptime_seconds": 100, "load_1m": 0.1, "cpu_count": 2,
                "memory_total_mb": 1000, "memory_used_mb": 300,
                "swap_total_mb": 0, "swap_used_mb": 0,
                "disk_total_gb": 40.0, "disk_free_gb": 30.0, "disk_used_percent": 25,
                "reboot_required": false
              },
              "network": {"rx_total_gb": 1.0, "tx_total_gb": 0.5},
              "pipeline": {
                "observations": 100, "checkpoints_active": 5,
                "errors_last_hour": 0, "devices": 1, "subscriptions": 0,
                "eta_targets": 0, "pushes_sent": 0, "db_size_mb": 10.0,
                "completeness_percent": 100
              },
              "certificate": {"days_left": 60},
              "backups": {"age_hours": 5.0, "stale": false},
              "problems": []
            }
        """.trimIndent()

        val t = json.decodeFromString(Api.Telemetry.serializer(), payload)

        // Старі поля читаються нормально.
        assertEquals(100, t.system.uptime_seconds)
        assertEquals(100L, t.pipeline.observations)
        assertEquals(60, t.certificate.days_left)

        // Нові поля відсутні → null / default.
        assertNull(t.system.load_5m)
        assertNull(t.system.snapshot_age_seconds)
        assertNull(t.system.stale)
        assertNull(t.pipeline.last_observation)
        assertNull(t.pipeline.runs_last_hour)
        assertNull(t.pipeline.alerts_pending)
        assertNull(t.pipeline.collecting_since)
        assertNull(t.certificate.error)
        assertNull(t.backups.last_run)
    }

    @Test fun `парсинг payload з усіма новими полями`() {
        val payload = """
            {
              "system": {
                "uptime_seconds": 100, "load_1m": 0.1, "load_5m": 0.2,
                "cpu_count": 2,
                "memory_total_mb": 1000, "memory_used_mb": 300,
                "swap_total_mb": 0, "swap_used_mb": 0,
                "disk_total_gb": 40.0, "disk_free_gb": 30.0, "disk_used_percent": 25,
                "reboot_required": false, "snapshot_age_seconds": 45, "stale": false
              },
              "network": {"rx_total_gb": 1.0, "tx_total_gb": 0.5},
              "pipeline": {
                "observations": 100, "checkpoints_active": 5,
                "errors_last_hour": 0, "devices": 1, "subscriptions": 0,
                "eta_targets": 0, "pushes_sent": 0, "db_size_mb": 10.0,
                "completeness_percent": 100,
                "last_observation": "2026-08-12T14:00:00Z",
                "runs_last_hour": 60, "alerts_pending": 0,
                "collecting_since": "2026-08-07T00:00:00Z"
              },
              "certificate": {"days_left": 60, "issuer": "Let's Encrypt", "error": null},
              "backups": {"age_hours": 5.0, "stale": false, "last_run": 1723465200},
              "problems": []
            }
        """.trimIndent()

        val t = json.decodeFromString(Api.Telemetry.serializer(), payload)

        assertEquals(0.2, t.system.load_5m!!, 0.001)
        assertEquals(45, t.system.snapshot_age_seconds)
        assertEquals(false, t.system.stale)
        assertEquals("2026-08-12T14:00:00Z", t.pipeline.last_observation)
        assertEquals(60, t.pipeline.runs_last_hour)
        assertEquals(0, t.pipeline.alerts_pending)
        assertEquals("2026-08-07T00:00:00Z", t.pipeline.collecting_since)
        assertEquals("Let's Encrypt", t.certificate.issuer)
        assertNull(t.certificate.error)
        assertEquals(1723465200L, t.backups.last_run)
    }

    @Test fun `parsing з stale=true правильно тегує проблему`() {
        val payload = """
            {
              "system": {
                "memory_total_mb": 0, "memory_used_mb": 0,
                "swap_total_mb": 0, "swap_used_mb": 0,
                "disk_total_gb": 0, "disk_free_gb": 0,
                "reboot_required": false,
                "snapshot_age_seconds": 900, "stale": true
              },
              "network": {"rx_total_gb": 0, "tx_total_gb": 0},
              "pipeline": {
                "observations": 0, "checkpoints_active": 0,
                "errors_last_hour": 0, "devices": 0, "subscriptions": 0,
                "eta_targets": 0, "pushes_sent": 0, "db_size_mb": 0.0,
                "completeness_percent": 0
              },
              "certificate": {},
              "backups": {},
              "problems": [
                {"kind": "telemetry_snapshot_stale", "detail": "не оновлювалось 15 хв"}
              ]
            }
        """.trimIndent()

        val t = json.decodeFromString(Api.Telemetry.serializer(), payload)

        assertEquals(true, t.system.stale)
        assertEquals(900, t.system.snapshot_age_seconds)
        assertTrue(t.problems.any { it.kind == "telemetry_snapshot_stale" })
    }
}
