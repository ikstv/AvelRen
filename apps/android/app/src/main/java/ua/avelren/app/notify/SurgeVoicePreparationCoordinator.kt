package ua.avelren.app.notify

import kotlinx.coroutines.ensureActive

class SurgeVoicePreparationCoordinator(private val prepare: suspend (Int, String) -> VoicePreparation) {
    suspend fun enable(checkpointId: Int, title: String, save: suspend () -> Unit): VoicePreparation {
        val result = prepare(checkpointId, title)
        if (result is VoicePreparation.Ready) {
            kotlinx.coroutines.currentCoroutineContext().ensureActive()
            save()
        }
        return result
    }
}
