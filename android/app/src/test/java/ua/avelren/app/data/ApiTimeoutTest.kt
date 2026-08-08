package ua.avelren.app.data

import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.client.request.get
import io.ktor.client.statement.bodyAsText
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import kotlinx.coroutines.delay
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import ua.avelren.app.data.DeviceStore.Credentials

class ApiTimeoutTest {
    @Test
    fun `ACK request times out at its per-request limit`() = runTest {
        val client = Api.clientFor(MockEngine {
            delay(100)
            respond(
                content = "ok",
                status = HttpStatusCode.OK,
                headers = headersOf("Content-Type", "text/plain"),
            )
        }, requestTimeoutMs = 100)

        val failure = runCatching {
            Api.ackWith(client, Credentials("device", "secret"), alertId = 1, kind = "threshold", requestTimeoutMs = 50)
        }
        assertTrue("ACK must be bounded by its request timeout", failure.isFailure)
        client.close()
    }

    @Test
    fun `ACK request override is stricter than the global request limit`() = runTest {
        val client = Api.clientFor(MockEngine {
            delay(75)
            respond("ordinary request completed", HttpStatusCode.OK)
        }, requestTimeoutMs = 100)

        val response = client.get("https://example.test/checkpoints")
        assertEquals("ordinary request completed", response.bodyAsText())
        client.close()
    }

    @Test
    fun `client applies the approved timeout policy to ordinary requests`() = runTest {
        val client = Api.clientFor(MockEngine {
            delay(101)
            respond("too late", HttpStatusCode.OK)
        }, requestTimeoutMs = 100)

        val failure = runCatching { client.get("https://example.test/checkpoints") }
        assertTrue("ordinary request must be bounded by the global request timeout", failure.isFailure)
        client.close()
    }
}
