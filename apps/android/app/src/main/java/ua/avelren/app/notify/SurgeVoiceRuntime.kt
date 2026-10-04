package ua.avelren.app.notify

sealed interface VoicePlaybackResult {
    data class Started(val nextAt: Long) : VoicePlaybackResult
    data object Deadline : VoicePlaybackResult
    data object NotPosted : VoicePlaybackResult
}

class SurgeVoicePlayback(private val schedule: SurgeVoiceSchedule, private val clock: () -> Long) {
    fun start(durationMs: Long, publish: () -> Boolean, silence: () -> Unit): VoicePlaybackResult {
        if (!schedule.canStart(clock(), durationMs)) return VoicePlaybackResult.Deadline
        if (!publish()) return VoicePlaybackResult.NotPosted
        val publishedAt = clock()
        if (!schedule.canStart(publishedAt, durationMs)) {
            silence()
            return VoicePlaybackResult.Deadline
        }
        return VoicePlaybackResult.Started(schedule.reserve(publishedAt, durationMs))
    }
}
object SurgeVoiceRuntime {
    fun recheck(alertActive: Boolean, audioAllowed: Boolean, cancel: () -> Unit, silence: () -> Unit): Boolean {
        if (!alertActive) { cancel(); return true }
        if (!audioAllowed) { silence(); return true }
        return false
    }
}
enum class VoicePresentationRoute { FALLBACK, VOICE, BLOCKED }
object SurgeVoicePresentationPolicy {
    fun route(assetReady: Boolean, state: VoiceChannelState?): VoicePresentationRoute =
        if (!assetReady || state?.problem == "voice_not_ready") VoicePresentationRoute.FALLBACK
        else if (state?.visible == true) VoicePresentationRoute.VOICE else VoicePresentationRoute.BLOCKED
}
object SurgeVoiceReadinessPolicy {
    fun problem(preparationFailure: String?, states: List<VoiceChannelState>): String? =
        preparationFailure ?: states.firstOrNull { !it.voiceAllowed }?.problem
}
