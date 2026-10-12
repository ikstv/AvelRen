package ua.avelren.app.data

import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test
import androidx.work.ListenableWorker
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import kotlinx.coroutines.async
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.yield
import java.io.IOException

internal class TestRecoveryRecords(var record: RecoveryRecord? = null) : RecoveryStore {
    var fail = false
    override suspend fun load() = record
    override suspend fun compareAndSet(expected: RecoveryRecord?, replacement: RecoveryRecord?): Boolean {
        if (fail || record != expected) return false
        record = replacement
        return true
    }
}

internal fun testCommitter(store: CredentialStore) = object : CredentialCommitter {
    override suspend fun commit(expected: DeviceStore.Credentials?, replacement: DeviceStore.Credentials?): Boolean {
        if (store.load() != expected) return false
        if (replacement == null) store.clear() else store.save(replacement)
        return true
    }
}

internal class WiringCredentials(seed: DeviceStore.Credentials? = DeviceStore.Credentials("valid", "secret")) : CredentialStore {
    var value = seed
    var clears = 0
    override fun load() = value
    override fun save(creds: DeviceStore.Credentials) { value = creds }
    override fun clear() { clears++; value = null }
}

internal class WiringTokens(var current: String = "canonical-X") : FcmTokenProvider {
    var deletions = 0
    override suspend fun currentToken() = current
    override suspend fun deleteCurrentToken() { deletions++; current = "replacement-Y" }
}

class FcmRecoveryWiringTest {
    @Test fun test_real_repository_delegation() = runTest {
        val updated = mutableListOf<String>()
        val repository = InstallationRepository(
            object : InstallationApi {
                override suspend fun registerDevice(fcmToken: String) = error("valid identity")
                override suspend fun updateToken(creds: DeviceStore.Credentials, fcmToken: String) { updated += fcmToken }
                override fun isStaleInstallation(exc: Throwable) = false
            },
            object : CredentialStore {
                override fun load() = DeviceStore.Credentials("valid", "secret")
                override fun save(creds: DeviceStore.Credentials) = error("valid identity")
                override fun clear() = error("valid identity")
            },
            WiringTokens("canonical-Y"),
            backgroundScope,
            recoveryStore = TestRecoveryRecords(),
            credentialCommitter = object : CredentialCommitter {
                override suspend fun commit(expected: DeviceStore.Credentials?, replacement: DeviceStore.Credentials?) = false
            },
        )
        repository.onNewFcmToken("obsolete-X")
        assertEquals(listOf("canonical-Y"), updated)
    }

    @Test fun test_valid_creds_stay_ready_pushblocked() = runTest {
        val store = WiringCredentials()
        val tokens = WiringTokens()
        val records = TestRecoveryRecords()
        val http = Api.clientFor(MockEngine {
            respond("""{"detail":{"code":"fcm_token_conflict"}}""", HttpStatusCode.Conflict,
                headersOf("Content-Type", "application/json"))
        })
        val api = object : InstallationApi {
            override suspend fun registerDevice(fcmToken: String) = error("must preserve identity")
            override suspend fun updateToken(creds: DeviceStore.Credentials, fcmToken: String) = Api.updateTokenWith(http, creds, fcmToken)
            override fun isStaleInstallation(exc: Throwable) = Api.isStaleInstallation(exc)
        }
        val repository = InstallationRepository(api, store, tokens, backgroundScope,
            records, testCommitter(store))
        try {
            repository.onNewFcmToken("ignored")
            assertEquals(InstallationState.Ready("valid"), repository.state.value)
            assertEquals(PushSyncState.ConflictBlocked, repository.pushState.value)
            assertEquals(0, store.clears)
            assertEquals(1, tokens.deletions)
            val incident = records.record!!
            repository.onNewFcmToken("late-X")
            assertEquals(incident, records.record)
            repository.retryBlocked()
            assertEquals(incident.incidentId, records.record!!.incidentId)
            assertEquals(1, records.record!!.completedRotations)
            assertEquals(PushSyncState.ConflictBlocked, repository.pushState.value)
            assertEquals(1, tokens.deletions)
        } finally { http.close() }
    }

    @Test fun test_worker_does_not_cancel_self() = runTest {
        val store = WiringCredentials()
        val tokens = WiringTokens()
        val records = TestRecoveryRecords(RecoveryRecord(1, 1,
            "11111111-1111-4111-8111-111111111111", 1, RecoveryPhase.PENDING, "canonical-X", null, 0))
        var enqueues = 0
        val scheduler = object : FcmTokenRetryScheduler {
            override suspend fun enqueue(): ScheduleResult { enqueues++; error("worker cannot replace itself") }
        }
        val http = Api.clientFor(MockEngine { request ->
            if ((request.body as io.ktor.http.content.TextContent).text.contains("canonical-X"))
                respond("""{"detail":{"code":"fcm_token_conflict"}}""", HttpStatusCode.Conflict, headersOf("Content-Type", "application/json"))
            else respond("", HttpStatusCode.OK)
        })
        val api = object : InstallationApi {
            override suspend fun registerDevice(fcmToken: String) = error("valid identity")
            override suspend fun updateToken(creds: DeviceStore.Credentials, fcmToken: String) = Api.updateTokenWith(http, creds, fcmToken)
            override fun isStaleInstallation(exc: Throwable) = Api.isStaleInstallation(exc)
        }
        val repository = InstallationRepository(api, store, tokens, backgroundScope,
            records, testCommitter(store), scheduler)
        try {
            assertTrue(runFcmTokenSync(repository) is ListenableWorker.Result.Success)
            assertEquals(1, tokens.deletions)
            assertEquals(0, enqueues)
            assertNull(records.record)
            assertEquals(PushSyncState.Synced, repository.pushState.value)
        } finally { http.close() }
    }

    @Test fun test_pendingY_afterX_success() = runTest {
        val entered = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        val store = WiringCredentials()
        val records = TestRecoveryRecords(RecoveryRecord(1, 1,
            "11111111-1111-4111-8111-111111111111", 1, RecoveryPhase.PENDING, "canonical-X", null, 0))
        val tokens = WiringTokens()
        val updated = mutableListOf<String>()
        val api = object : InstallationApi {
            override suspend fun registerDevice(fcmToken: String) = error("valid identity")
            override fun isStaleInstallation(exc: Throwable) = false
            override suspend fun updateToken(creds: DeviceStore.Credentials, fcmToken: String) {
                updated += fcmToken
                if (fcmToken == "canonical-X") { entered.complete(Unit); release.await() }
                else throw IOException("offline")
            }
        }
        val repository = InstallationRepository(api, store, tokens, backgroundScope, records, testCommitter(store))
        val x = async { runFcmTokenSync(repository) }
        entered.await()
        tokens.current = "canonical-Y"
        val y = async { repository.onNewFcmToken("late-X") }
        yield()
        release.complete(Unit)
        assertTrue("successful obsolete X cannot finish a worker with Y still pending",
            x.await() is ListenableWorker.Result.Retry)
        y.await()
        assertEquals("canonical-Y", records.record!!.candidateToken)
        assertEquals(PushSyncState.Retrying, repository.pushState.value)
        assertTrue(runFcmTokenSync(repository) is ListenableWorker.Result.Retry)
        assertTrue(updated.contains("canonical-Y"))
    }
}
