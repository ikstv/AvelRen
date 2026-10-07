package ua.avelren.app.data

import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.client.plugins.ClientRequestException
import io.ktor.http.HttpMethod
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

class PublicCpuApiTest {
    @Test fun cpuUsesPublicRouteWithoutInstallationCredentials() = runTest {
        val client = Api.clientFor(MockEngine { request ->
            assertEquals(HttpMethod.Get, request.method)
            assertEquals("/api/server/status", request.url.encodedPath)
            assertNull(request.headers["X-Device-Id"])
            assertNull(request.headers["X-Device-Secret"])
            respond("""{"cpu_percent":0,"measured_at":"2026-10-07T12:00:00Z","sample_seconds":1,"stale":false}""",
                headers = headersOf("Content-Type", "application/json"))
        })
        try { assertEquals(0.0, Api.serverCpuStatusWith(client).cpu_percent!!, 0.001) }
        finally { client.close() }
    }

    @Test fun oldServer404IsUnavailableNotZero() = runTest {
        val client = Api.clientFor(MockEngine {
            respond("""{"detail":"Not Found"}""", HttpStatusCode.NotFound,
                headersOf("Content-Type", "application/json"))
        })
        try { Api.serverCpuStatusWith(client); fail("404 must not become CPU zero") }
        catch (error: ClientRequestException) { assertEquals(HttpStatusCode.NotFound, error.response.status) }
        finally { client.close() }
    }
}
