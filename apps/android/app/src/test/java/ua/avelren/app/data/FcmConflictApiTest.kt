package ua.avelren.app.data

import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.client.plugins.ClientRequestException
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test

class FcmConflictApiTest {
    @Test fun test_legacy_success_contract_keeps_credentials_and_authentication() = runTest {
        var requests = 0
        val http = Api.clientFor(MockEngine { request ->
            requests++
            if (requests == 1) {
                assertEquals("POST", request.method.value)
                assertTrue(request.url.encodedPath.endsWith("/devices"))
                assertNull(request.headers["X-Device-Secret"])
                respond("""{"device_id":"legacy-id","device_secret":"legacy-secret"}""",
                    HttpStatusCode.Created, headersOf("Content-Type", "application/json"))
            } else {
                assertEquals("PUT", request.method.value)
                assertTrue(request.url.encodedPath.endsWith("/devices/token"))
                assertEquals("legacy-id", request.headers["X-Device-Id"])
                assertEquals("legacy-secret", request.headers["X-Device-Secret"])
                respond("""{"ok":true}""", HttpStatusCode.OK,
                    headersOf("Content-Type", "application/json"))
            }
        })
        try {
            val credentials = Api.registerDeviceWith(http, "legacy-token")
            assertEquals(DeviceStore.Credentials("legacy-id", "legacy-secret"), credentials)
            Api.updateTokenWith(http, credentials, "replacement-token")
            assertEquals(2, requests)
        } finally { http.close() }
    }

    private suspend fun failure(status: HttpStatusCode, body: String, put: Boolean): Throwable {
        val http = Api.clientFor(MockEngine {
            respond(body, status, headersOf("Content-Type", "application/json"))
        })
        return try {
            if (put) Api.updateTokenWith(http, DeviceStore.Credentials("private-id", "private-secret"), "private-token")
            else Api.registerDeviceWith(http, "private-token")
            error("expected rejection")
        } catch (e: Throwable) { e } finally { http.close() }
    }

    @Test fun test_only_typed409_rotates() = runTest {
        for (put in listOf(false, true)) {
            val error = failure(HttpStatusCode.Conflict,
                """{"detail":{"code":"fcm_token_conflict","ignored":"private-token"}}""", put)
            assertEquals("TokenConflictException", error.javaClass.simpleName)
            assertFalse(Api.isStaleInstallation(error))
            assertNull(error.cause)
            assertFalse(error.toString().contains("private"))
        }
    }

    @Test fun test_unrelated409_terminal() = runTest {
        for (body in listOf("""{"detail":{"code":"other"}}""", """{"code":"fcm_token_conflict"}""", "invalid")) {
            val error = failure(HttpStatusCode.Conflict, body, true)
            assertTrue(error is ClientRequestException)
            assertTrue(classifyTokenSyncFailure(error) is PendingTokenSyncOutcome.TerminalFailure)
        }
    }

    @Test fun test_503_retry_pending() = runTest {
        val error = failure(HttpStatusCode.ServiceUnavailable,
            """{"detail":{"code":"fcm_token_conflict"}}""", false)
        assertTrue(classifyTokenSyncFailure(error) is PendingTokenSyncOutcome.RetryableFailure)
    }

    @Test fun test_401_stays_separate() = runTest {
        val error = failure(HttpStatusCode.Unauthorized,
            """{"detail":{"code":"fcm_token_conflict"}}""", true)
        assertTrue(Api.isStaleInstallation(error))
    }
}
