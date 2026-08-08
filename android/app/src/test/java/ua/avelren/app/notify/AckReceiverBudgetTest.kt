package ua.avelren.app.notify

import kotlinx.coroutines.TimeoutCancellationException
import kotlinx.coroutines.delay
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.fail
import org.junit.Test

class AckReceiverBudgetTest {
    @Test
    fun `operation completes within receiver budget`() = runTest {
        val result = withinAckReceiverBudget(timeoutMs = 100) {
            delay(50)
            "acknowledged"
        }

        assertEquals("acknowledged", result)
    }

    @Test
    fun `stuck recovery-like operation is cancelled by receiver budget`() = runTest {
        try {
                withinAckReceiverBudget(timeoutMs = 100) {
                    delay(101)
                }
            fail("receiver budget must cancel a stuck operation")
        } catch (_: TimeoutCancellationException) {
            // expected
        }
    }
}
