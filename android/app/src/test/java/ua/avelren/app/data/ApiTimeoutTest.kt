package ua.avelren.app.data

import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.client.plugins.HttpRequestTimeoutException
import io.ktor.client.request.get
import io.ktor.client.statement.bodyAsText
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import kotlinx.coroutines.delay
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.fail
import org.junit.Test
import ua.avelren.app.data.DeviceStore.Credentials

class ApiTimeoutTest {
    @Test
    fun `ACK request times out at its per-request limit`() = runTest {
        val client = Api.clientFor(MockEngine {
            delay(75)
            respond(
                content = "ok",
                status = HttpStatusCode.OK,
                headers = headersOf("Content-Type", "text/plain"),
            )
        }, requestTimeoutMs = 100)

        try {
            Api.ackWith(
                client,
                Credentials("device", "secret"),
                alertId = 1,
                kind = "threshold",
                requestTimeoutMs = 50,
            )
            fail("ACK must time out before the 75ms handler delay")
        } catch (_: HttpRequestTimeoutException) {
            // 50 ACK < 75 delay < 100 global: the per-request override fired.
        }
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

        try {
            client.get("https://example.test/checkpoints")
            fail("ordinary request must time out after the 100ms global limit")
        } catch (_: HttpRequestTimeoutException) {
            // 101 delay > 100 global request timeout.
        }
        client.close()
    }
}
