package ua.avelren.app.notify

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

class SurgeVoicePreparationCoordinatorTest {
    @Test fun failureDoesNotCreateServerSubscription() = runTest {
        var saves = 0
        val coordinator = SurgeVoicePreparationCoordinator { _, _ -> VoicePreparation.Failure("uk_unavailable") }
        assertEquals(VoicePreparation.Failure("uk_unavailable"), coordinator.enable(17, "Чоп") { saves++ })
        assertEquals(0, saves)
    }
    @Test fun readyVoicesPrecedeExactlyOneSaveWithCorrectCheckpointAndTitle() = runTest {
        val events = mutableListOf<String>()
        val coordinator = SurgeVoicePreparationCoordinator { id, title ->
            events += "prepare:$id:$title"
            VoicePreparation.Ready(emptyList())
        }
        assertTrue(coordinator.enable(29, "Ягодин для порожніх вантажівок") { events += "save" } is VoicePreparation.Ready)
        assertEquals(listOf("prepare:29:Ягодин для порожніх вантажівок", "save"), events)
    }
    @Test fun cancellationPropagatesWithoutSave() = runTest {
        var saves = 0
        val coordinator = SurgeVoicePreparationCoordinator { _, _ -> throw CancellationException("cancel") }
        try { coordinator.enable(17, "Чоп") { saves++ }; fail("Expected cancellation") }
        catch (_: CancellationException) { }
        assertEquals(0, saves)
    }
    @Test fun saveFailureIsNotReportedAsReady() = runTest {
        val coordinator = SurgeVoicePreparationCoordinator { _, _ -> VoicePreparation.Ready(emptyList()) }
        try { coordinator.enable(17, "Чоп") { throw IllegalStateException("offline") }; fail("Expected save failure") }
        catch (error: IllegalStateException) { assertEquals("offline", error.message) }
    }
}
