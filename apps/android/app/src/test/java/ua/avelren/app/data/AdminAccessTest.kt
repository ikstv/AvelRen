package ua.avelren.app.data

import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.client.plugins.ClientRequestException
import io.ktor.http.HttpMethod
import io.ktor.http.HttpStatusCode
import io.ktor.http.content.TextContent
import io.ktor.http.headersOf
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.fail
import org.junit.Test

class AdminAccessTest {
    private val credentials = DeviceStore.Credentials("installation", "test-secret")

    @Test
    fun `status uses authenticated GET without PIN`() = runTest {
        val client = Api.clientFor(MockEngine { request ->
            assertEquals(HttpMethod.Get, request.method)
            assertEquals("/api/admin/access", request.url.encodedPath)
            assertEquals("installation", request.headers["X-Device-Id"])
            assertEquals("test-secret", request.headers["X-Device-Secret"])
            assertFalse(request.url.parameters.contains("pin"))
            respond("""{"state":"awaiting_approval"}""", headers = headersOf("Content-Type", "application/json"))
        })
        try {
            assertEquals("awaiting_approval", Api.adminAccessWith(client, credentials).state)
        } finally { client.close() }
    }

    @Test
    fun `PIN is posted in body and lock comes from server`() = runTest {
        val client = Api.clientFor(MockEngine { request ->
            assertEquals(HttpMethod.Post, request.method)
            assertEquals("test-secret", request.headers["X-Device-Secret"])
            assertEquals("""{"pin":"7392"}""", (request.body as TextContent).text)
            assertFalse(request.url.toString().contains("7392"))
            respond(
                """{"state":"blocked","attempts_remaining":0,"locked_until":"2026-09-23T13:00:00Z"}""",
                headers = headersOf("Content-Type", "application/json"),
            )
        })
        try {
            val result = Api.adminAccessWith(client, credentials, "7392")
            assertEquals("blocked", result.state)
            assertEquals(0, result.attempts_remaining)
            assertEquals("2026-09-23T13:00:00Z", result.locked_until)
        } finally { client.close() }
    }

    @Test
    fun `server denial is not treated as successful authentication`() = runTest {
        val client = Api.clientFor(MockEngine {
            respond("""{"detail":"denied"}""", HttpStatusCode.Forbidden,
                headersOf("Content-Type", "application/json"))
        })
        try {
            Api.adminAccessWith(client, credentials, "7392")
            fail("Server rejection must not grant access")
        } catch (_: ClientRequestException) {
            // There is no local PIN comparison or offline promotion.
        } finally { client.close() }
    }
}
