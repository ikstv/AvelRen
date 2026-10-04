package ua.avelren.app.notify

import org.junit.Assert.*
import org.junit.Test

class SurgeVoiceScheduleTest {
    @Test fun nextPhraseWaitsForAudioAndOneSecondGap() {
        val schedule = SurgeVoiceSchedule(0)
        assertEquals(4000L, schedule.reserve(0, 3000))
        assertFalse(schedule.canStart(3999, 3000))
        assertTrue(schedule.canStart(4000, 3000))
    }
    @Test fun laterEventsCannotExtendOriginalDeadline() {
        val schedule = SurgeVoiceSchedule(10_000)
        schedule.reserve(10_000, 3000)
        schedule.reserve(100_000, 3000)
        assertFalse(schedule.canStart(160_001, 10_000))
        assertFalse(schedule.canStart(170_000, 1))
    }
    @Test fun badDurationsAndPrematureReservationsAreRejected() {
        val schedule = SurgeVoiceSchedule(0)
        assertFalse(schedule.canStart(0, 0))
        assertFalse(schedule.canStart(0, 15_001))
        schedule.reserve(0, 3000)
        assertThrows(IllegalArgumentException::class.java) { schedule.reserve(1, 3000) }
    }
}
