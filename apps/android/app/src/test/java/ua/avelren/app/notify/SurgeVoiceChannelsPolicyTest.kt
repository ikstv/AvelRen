package ua.avelren.app.notify

import org.junit.Assert.*
import org.junit.Test

class SurgeVoiceChannelsPolicyTest {
    @Test fun missingSpecificChannelIsIncompletePreparationRatherThanUserBlock() {
        assertEquals(VoiceChannelState(true, false, "voice_not_ready"), SurgeVoiceChannelPolicy.evaluate(true, 4, true, null, false, false))
        assertEquals(VoiceChannelState(false, false, "notification_blocked"), SurgeVoiceChannelPolicy.evaluate(true, 0, true, null, false, false))
    }
    @Test fun appAndEitherChannelBlockPreventVisibility() {
        assertEquals(VoiceChannelState(false, false, "notification_blocked"), state(app = false))
        assertEquals(VoiceChannelState(false, false, "notification_blocked"), state(legacy = 0))
        assertEquals(VoiceChannelState(false, false, "notification_blocked"), state(voice = 0))
    }
    @Test fun quietLegacySettingsCannotBeBypassedWithNewChannel() {
        assertFalse(state(legacy = 2).voiceAllowed)
        assertFalse(state(legacySound = false).voiceAllowed)
        assertTrue(state(legacy = 2).visible)
    }
    @Test fun quietSpecificChannelDoesNotSpeak() {
        assertFalse(state(voice = 2).voiceAllowed)
        assertFalse(state(voiceSound = false).voiceAllowed)
    }
    @Test fun customSoundIsReportedWithoutPlayingWrongVoice() {
        assertEquals(VoiceChannelState(true, false, "voice_sound_changed"), state(matches = false))
        assertEquals(VoiceChannelState(true, true, null), state())
    }
    private fun state(app: Boolean = true, legacy: Int = 4, legacySound: Boolean = true,
        voice: Int = 4, voiceSound: Boolean = true, matches: Boolean = true) =
        SurgeVoiceChannelPolicy.evaluate(app, legacy, legacySound, voice, voiceSound, matches)
}
