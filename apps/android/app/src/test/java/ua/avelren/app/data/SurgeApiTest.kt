package ua.avelren.app.data

import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.client.plugins.ServerResponseException
import io.ktor.http.*
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

class SurgeApiTest {
    @Test fun `ACK sends own credentials and treats old missing alert as terminal`() = runTest {
        val client = Api.clientFor(MockEngine { request ->
            assertEquals("/api/surge-alerts/42/ack", request.url.encodedPath)
            assertEquals(HttpMethod.Post, request.method)
            assertEquals("fixture-device", request.headers["X-Device-Id"])
            assertEquals("fixture-secret", request.headers["X-Device-Secret"])
            respond("not found", HttpStatusCode.NotFound)
        })
        try { SurgeApi(client, "https://example.test/api").ack(DeviceStore.Credentials("fixture-device", "fixture-secret"), 42) }
        finally { client.close() }
    }
    @Test fun `unavailable service is not treated as successful ACK`() = runTest {
        val client = Api.clientFor(MockEngine { respond("offline", HttpStatusCode.ServiceUnavailable) })
        try {
            SurgeApi(client, "https://example.test/api").ack(DeviceStore.Credentials("fixture", "fixture"), 42)
            fail("503 must retain pending ACK")
        } catch (_: ServerResponseException) { }
        finally { client.close() }
    }
}
