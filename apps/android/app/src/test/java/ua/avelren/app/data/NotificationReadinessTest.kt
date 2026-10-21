package ua.avelren.app.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class NotificationReadinessTest {
    private val observed = NotificationReadiness.Snapshot(
        runtimePermissionGranted = true, appNotificationsEnabled = true,
        queueChannelExists = true, queueChannelImportance = 4,
        queueChannelSoundUri = "content://settings/system/alarm_alert",
        alarmVolume = 4, alarmMaxVolume = 7, ringerMode = 2, interruptionFilter = 1,
    )

    @Test fun `permission or app or channel block takes precedence over sound`() {
        listOf(
            observed.copy(runtimePermissionGranted = false, alarmVolume = 0),
            observed.copy(appNotificationsEnabled = false),
            observed.copy(queueChannelImportance = 0),
        ).forEach { assertEquals("Сповіщення заблоковано", NotificationReadiness.evaluate(it).title) }
    }

    @Test fun `missing sound low importance and zero alarm volume need attention`() {
        listOf(observed.copy(queueChannelSoundUri = null), observed.copy(queueChannelImportance = 2),
            observed.copy(alarmVolume = 0)).forEach {
            assertEquals("Звук потребує уваги", NotificationReadiness.evaluate(it).title)
        }
    }

    @Test fun `absent channel and unreadable snapshot never imply readiness`() {
        listOf(NotificationReadiness.Snapshot(), observed.copy(queueChannelExists = false,
            queueChannelImportance = null, queueChannelSoundUri = null)).forEach {
            val result = NotificationReadiness.evaluate(it)
            assertEquals("Потрібно перевірити налаштування", result.title)
            assertTrue(result.indicators.any { row -> row.status == NotificationReadiness.Status.Unknown })
        }
    }

    @Test fun `silent ringer does not claim alarm usage is muted`() {
        val result = NotificationReadiness.evaluate(observed.copy(ringerMode = 0))
        assertEquals("Сповіщення дозволені", result.title)
        assertTrue(result.indicators.first { it.title == "Режим дзвінка" }.detail.contains("не визначає"))
    }

    @Test fun `dnd modes carry caution even when alarm sound is configured`() {
        listOf(2, 3, 4).forEach { filter ->
            val result = NotificationReadiness.evaluate(observed.copy(interruptionFilter = filter))
            assertEquals(NotificationReadiness.Status.Attention,
                result.indicators.first { it.title == "Не турбувати" }.status)
            assertEquals("Режим «Не турбувати» активний", result.title)
        }
    }

    @Test fun `observed settings never promise sound or delivery`() {
        val result = NotificationReadiness.evaluate(observed)
        assertEquals("Сповіщення дозволені", result.title)
        assertTrue(result.detail.contains("Звук залежить"))
    }

    @Test fun `active dnd does not hide blocked quiet or unknown settings`() {
        assertEquals("Сповіщення заблоковано", NotificationReadiness.evaluate(
            observed.copy(interruptionFilter = 2, appNotificationsEnabled = false)).title)
        assertEquals("Звук потребує уваги", NotificationReadiness.evaluate(
            observed.copy(interruptionFilter = 3, alarmVolume = 0)).title)
        assertEquals("Потрібно перевірити налаштування", NotificationReadiness.evaluate(
            observed.copy(interruptionFilter = 4, appNotificationsEnabled = null)).title)
    }
}
