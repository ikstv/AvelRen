package ua.avelren.app.notify

import org.junit.Assert.*
import org.junit.Test

class SurgeVoiceRuntimeTest {
    @Test fun crossingDeadlineInsidePublisherStopsSoundAndPreservesSilentAlert() {
        var clock = 143_999L
        val events = mutableListOf<String>()
        val playback = SurgeVoicePlayback(SurgeVoiceSchedule(0)) { clock }
        assertEquals(VoicePlaybackResult.Deadline, playback.start(15_000,
            { events += "post"; clock = 144_001; true }, { events += "silent" }))
        assertEquals(listOf("post", "silent"), events)
        assertEquals(VoicePlaybackResult.Deadline, playback.start(15_000, { fail("No replay"); true }, {}))
    }
    @Test fun successfulPublisherReservesFromActualPublicationTime() {
        var clock = 0L
        val playback = SurgeVoicePlayback(SurgeVoiceSchedule(0)) { clock }
        assertEquals(VoicePlaybackResult.Started(4500), playback.start(3000, { clock = 500; true }, { fail("Should stay audible") }))
        clock = 4499
        assertEquals(VoicePlaybackResult.Deadline, playback.start(3000, { fail("No overlapping sound"); true }, {}))
    }
    @Test fun dndOrMissingMetadataSilencesButDoesNotCancelActiveAlert() {
        val events = mutableListOf<String>()
        assertTrue(SurgeVoiceRuntime.recheck(true, false, { events += "cancel" }, { events += "silent" }))
        assertEquals(listOf("silent"), events)
    }
    @Test fun acknowledgedOrExpiredAlertIsRemoved() {
        val events = mutableListOf<String>()
        assertTrue(SurgeVoiceRuntime.recheck(false, true, { events += "cancel" }, { events += "silent" }))
        assertEquals(listOf("cancel"), events)
        assertFalse(SurgeVoiceRuntime.recheck(true, true, { fail("No cancellation") }, { fail("No silence") }))
    }
    @Test fun missingChannelUsesFallbackButExplicitBlockDoesNot() {
        val missing = VoiceChannelState(true, false, "voice_not_ready")
        assertEquals(VoicePresentationRoute.FALLBACK, SurgeVoicePresentationPolicy.route(true, missing))
        assertEquals(VoicePresentationRoute.BLOCKED, SurgeVoicePresentationPolicy.route(true, VoiceChannelState(false, false, "notification_blocked")))
        assertEquals(VoicePresentationRoute.FALLBACK, SurgeVoicePresentationPolicy.route(false, null))
    }
    @Test fun foregroundReadinessClearsRecoveredProblemAndReadsCurrentChannelSettings() {
        assertNull(SurgeVoiceReadinessPolicy.problem(null, listOf(VoiceChannelState(true, true, null))))
        assertEquals("notification_silent", SurgeVoiceReadinessPolicy.problem(null, listOf(VoiceChannelState(true, false, "notification_silent"))))
        assertEquals("voice_sound_changed", SurgeVoiceReadinessPolicy.problem(null, listOf(VoiceChannelState(true, false, "voice_sound_changed"))))
        assertEquals("uk_unavailable", SurgeVoiceReadinessPolicy.problem("uk_unavailable", emptyList()))
    }
}
