package ua.avelren.app.data

import androidx.work.ListenableWorker
import androidx.work.ExistingWorkPolicy
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import io.ktor.client.engine.mock.MockEngine
import io.ktor.client.engine.mock.respond
import io.ktor.http.HttpStatusCode
import io.ktor.http.headersOf
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.junit.Assert.*
import org.junit.Test
import java.io.IOException

@OptIn(ExperimentalCoroutinesApi::class)
class FcmRecoveryFinalRegressionTest {
    private fun pending() = RecoveryRecord(1, 1,
        "11111111-1111-4111-8111-111111111111", 1, RecoveryPhase.PENDING, "canonical-X", null, 0)
    private fun blocked() = pending().copy(phase = RecoveryPhase.CONFLICT_BLOCKED,
        candidateToken = "replacement-Y", rotationSourceToken = "canonical-X", completedRotations = 1)

    private val foregroundOwner = object : LifecycleOwner {
        override val lifecycle: Lifecycle get() = error("observer does not inspect owner state")
    }

    // The same adapter used in production must never cancel an already running job.
    @Test fun actual_scheduler_preserves_running_work_and_acknowledges_successor() = runTest {
        val activeWorker = Job()
        val acknowledge = CompletableDeferred<Unit>()
        var successor = false
        val scheduler = WorkManagerFcmTokenRetryScheduler { name, policy ->
            assertEquals("avelren_fcm_token_sync", name)
            when (policy) {
                ExistingWorkPolicy.REPLACE -> activeWorker.cancel()
                ExistingWorkPolicy.APPEND_OR_REPLACE -> successor = true
                else -> Unit
            }
            acknowledge.await()
        }
        val enqueue = async { scheduler.enqueue() }
        runCurrent()
        try {
            assertTrue("genuine token change must not cancel running HTTP", activeWorker.isActive)
            assertTrue("successor must not depend on KEEP accepting an active worker", successor)
            assertFalse("enqueue requires an operation acknowledgement", enqueue.isCompleted)
        } finally { acknowledge.complete(Unit); activeWorker.cancel() }
        assertEquals(ScheduleResult.Enqueued, enqueue.await())
    }

    // Actual process observer must resume failed handoff, with acknowledged scheduling before HTTP.
    @Test fun foreground_entry_recovers_failed_enqueue_with_same_identity_after_ack() = runTest {
        val store = WiringCredentials()
        val records = TestRecoveryRecords()
        val tokens = WiringTokens("provider-Z")
        val acknowledge = CompletableDeferred<Unit>()
        var schedulingAvailable = false
        var schedulingStarted = false
        var acknowledged = false
        val updated = mutableListOf<String>()
        val repository = InstallationRepository(object : InstallationApi {
            override suspend fun registerDevice(fcmToken: String) = error("preserve identity")
            override suspend fun updateToken(creds: DeviceStore.Credentials, fcmToken: String) {
                assertTrue("ack before HTTP", acknowledged)
                assertEquals(DeviceStore.Credentials("valid", "secret"), creds)
                updated += fcmToken
            }
            override fun isStaleInstallation(exc: Throwable) = false
        }, store, tokens, backgroundScope, records, testCommitter(store), object : FcmTokenRetryScheduler {
            override suspend fun enqueue(): ScheduleResult {
                if (!schedulingAvailable) return ScheduleResult.Failed(IOException())
                schedulingStarted = true
                acknowledge.await()
                acknowledged = true
                return ScheduleResult.Enqueued
            }
        })
        repository.onNewFcmToken("delayed callback")
        val durable = records.record!!
        assertTrue(updated.isEmpty())
        assertEquals(PushSyncState.Retrying, repository.pushState.value)
        val observer = InstallationForegroundRecovery(repository, backgroundScope)
        observer.onResume(foregroundOwner)
        runCurrent()
        assertEquals("another failed enqueue must leave the handoff recoverable", durable, records.record)
        assertTrue("failed foreground enqueue cannot fall through to HTTP", updated.isEmpty())
        schedulingAvailable = true
        observer.onResume(foregroundOwner)
        runCurrent()
        assertTrue("foreground entry must attempt scheduling", schedulingStarted)
        assertEquals(durable, records.record)
        assertTrue(updated.isEmpty())
        acknowledge.complete(Unit)
        runCurrent()
        assertEquals(listOf("provider-Z"), updated)
        assertEquals(InstallationState.Ready("valid"), repository.state.value)
        assertEquals(PushSyncState.Synced, repository.pushState.value)
        assertNull(records.record)
        observer.onResume(foregroundOwner)
        runCurrent()
        assertNull("resume without pending must not create another incident", records.record)
        assertEquals(listOf("provider-Z"), updated)
        assertEquals(0, tokens.deletions)
        assertEquals(0, store.clears)
    }

    // Advancing a generation for the same canonical Y would discard a successful POST.
    @Test fun same_canonical_callback_during_worker_replacement_post_keeps_credentials() = runTest {
        val store = WiringCredentials(null)
        val records = TestRecoveryRecords(pending()) // acknowledged persisted worker
        val tokens = WiringTokens()
        val entered = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        val posts = mutableListOf<String>()
        var unexpectedEnqueue = false
        var workerJob: Job? = null
        val http = Api.clientFor(MockEngine { request ->
            val body = (request.body as io.ktor.http.content.TextContent).text
            posts += body
            if (body.contains("canonical-X")) respond(
                """{"detail":{"code":"fcm_token_conflict"}}""", HttpStatusCode.Conflict,
                headersOf("Content-Type", "application/json"))
            else {
                entered.complete(Unit)
                release.await()
                respond("""{"device_id":"replacement-device","device_secret":"replacement-secret"}""",
                    HttpStatusCode.Created, headersOf("Content-Type", "application/json"))
            }
        })
        val api = object : InstallationApi {
            override suspend fun registerDevice(fcmToken: String) = Api.registerDeviceWith(http, fcmToken)
            override suspend fun updateToken(creds: DeviceStore.Credentials, fcmToken: String) = error("POST only")
            override fun isStaleInstallation(exc: Throwable) = Api.isStaleInstallation(exc)
        }
        val repository = InstallationRepository(api, store, tokens, backgroundScope, records,
            testCommitter(store), WorkManagerFcmTokenRetryScheduler { _, policy ->
                unexpectedEnqueue = true
                if (policy == ExistingWorkPolicy.REPLACE) workerJob?.cancel()
            })
        try {
            val worker = async { runFcmTokenSync(repository) }
            workerJob = worker
            entered.await()
            val attaching = records.record!!
            try {
                val callback = async { repository.onNewFcmToken("delayed canonical-X") }
                runCurrent()
                assertEquals("same candidate must retain the complete active record", attaching, records.record)
                assertFalse("callback must not schedule/cancel its active worker", unexpectedEnqueue)
                assertTrue(worker.isActive)
                callback.await()
            } finally { release.complete(Unit) }
            assertTrue(worker.await() is ListenableWorker.Result.Success)
            assertEquals(DeviceStore.Credentials("replacement-device", "replacement-secret"), store.value)
            assertEquals(InstallationState.Ready("replacement-device"), repository.state.value)
            assertEquals(PushSyncState.Synced, repository.pushState.value)
            assertNull(records.record)
            assertEquals(2, posts.size)
            assertEquals(1, tokens.deletions)
        } finally { release.complete(Unit); http.close() }
    }

    // A new process must discover Z without needing another callback or user retry.
    @Test fun blocked_recreation_discovers_new_sdk_token_without_resetting_budget() = runTest {
        val original = blocked()
        val store = WiringCredentials()
        val records = TestRecoveryRecords(original)
        val tokens = WiringTokens("provider-Z")
        val attempted = mutableListOf<String>()
        var enqueued = false
        val repository = InstallationRepository(object : InstallationApi {
            override suspend fun registerDevice(fcmToken: String) = error("valid identity")
            override suspend fun updateToken(creds: DeviceStore.Credentials, fcmToken: String) {
                assertTrue(enqueued)
                assertEquals(original.incidentId, records.record!!.incidentId)
                assertEquals(1, records.record!!.completedRotations)
                attempted += fcmToken
                throw TokenConflictException()
            }
            override fun isStaleInstallation(exc: Throwable) = false
        }, store, tokens, backgroundScope, records, testCommitter(store), object : FcmTokenRetryScheduler {
            override suspend fun enqueue(): ScheduleResult { enqueued = true; return ScheduleResult.Enqueued }
        })
        repository.initialize()
        assertEquals(listOf("provider-Z"), attempted)
        assertEquals(RecoveryPhase.CONFLICT_BLOCKED, records.record!!.phase)
        assertEquals(1, records.record!!.completedRotations)
        assertEquals(0, tokens.deletions)
        assertEquals(DeviceStore.Credentials("valid", "secret"), store.value)
    }

    @Test fun blocked_recreation_with_unchanged_sdk_token_is_inert() = runTest {
        val original = blocked()
        val store = WiringCredentials()
        val records = TestRecoveryRecords(original)
        val tokens = WiringTokens("replacement-Y")
        val repository = InstallationRepository(object : InstallationApi {
            override suspend fun registerDevice(fcmToken: String) = error("no HTTP")
            override suspend fun updateToken(creds: DeviceStore.Credentials, fcmToken: String) = error("no HTTP")
            override fun isStaleInstallation(exc: Throwable) = false
        }, store, tokens, backgroundScope, records, testCommitter(store), object : FcmTokenRetryScheduler {
            override suspend fun enqueue(): ScheduleResult = error("no enqueue")
        })
        repository.initialize()
        assertEquals(original, records.record)
        assertEquals(PushSyncState.ConflictBlocked, repository.pushState.value)
        assertEquals(0, tokens.deletions)
    }

    // A terminal HTTP rejection must not claim that an automatic retry is running.
    @Test fun unrelated_terminal_http_errors_are_visible_without_rotation() = runTest {
        for (status in listOf(400, 403, 422, 409)) {
            val store = WiringCredentials()
            val records = TestRecoveryRecords(pending())
            val tokens = WiringTokens()
            var requests = 0
            val http = Api.clientFor(MockEngine {
                requests++
                respond("""{"detail":{"code":"unrelated_rejection"}}""", HttpStatusCode.fromValue(status),
                    headersOf("Content-Type", "application/json"))
            })
            val repository = InstallationRepository(object : InstallationApi {
                override suspend fun registerDevice(fcmToken: String) = error("valid identity")
                override suspend fun updateToken(creds: DeviceStore.Credentials, fcmToken: String) = Api.updateTokenWith(http, creds, fcmToken)
                override fun isStaleInstallation(exc: Throwable) = Api.isStaleInstallation(exc)
            }, store, tokens, backgroundScope, records, testCommitter(store))
            try {
                assertTrue(runFcmTokenSync(repository) is ListenableWorker.Result.Failure)
                assertEquals(PushSyncState.Rejected, repository.pushState.value)
                assertEquals(0, tokens.deletions)
                assertEquals(DeviceStore.Credentials("valid", "secret"), store.value)
                assertNotNull(records.record)
                val rejected = records.record!!
                repository.onNewFcmToken("unchanged SDK token")
                val observer = InstallationForegroundRecovery(repository, backgroundScope)
                observer.onResume(foregroundOwner)
                runCurrent()
                assertTrue(runFcmTokenSync(repository) is ListenableWorker.Result.Failure)
                assertEquals("unchanged automatic entries must not retry terminal rejection", 1, requests)
                assertEquals(rejected, records.record)
                assertEquals(PushSyncState.Rejected, repository.pushState.value)
                repository.retryBlocked() // same explicit user action as the status button
                assertEquals(2, requests)
                assertEquals(PushSyncState.Rejected, repository.pushState.value)
                assertEquals(rejected.incidentId, records.record!!.incidentId)
                assertEquals(0, records.record!!.completedRotations)
                assertEquals(0, tokens.deletions)
            } finally { http.close() }
        }
    }

    // A terminal result for obsolete X must not fail the appended successor for Y.
    @Test fun genuine_new_candidate_survives_obsolete_terminal_worker_result() = runTest {
        val store = WiringCredentials()
        val records = TestRecoveryRecords(pending())
        val tokens = WiringTokens()
        val entered = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        val updates = mutableListOf<String>()
        val policies = mutableListOf<ExistingWorkPolicy>()
        var activeWorker: Job? = null
        val http = Api.clientFor(MockEngine { request ->
            val body = (request.body as io.ktor.http.content.TextContent).text
            updates += body
            if (body.contains("canonical-X")) {
                entered.complete(Unit)
                release.await()
                respond("""{"detail":"unrelated"}""", HttpStatusCode.Forbidden,
                    headersOf("Content-Type", "application/json"))
            } else respond("", HttpStatusCode.OK)
        })
        val repository = InstallationRepository(object : InstallationApi {
            override suspend fun registerDevice(fcmToken: String) = error("valid identity")
            override suspend fun updateToken(creds: DeviceStore.Credentials, fcmToken: String) = Api.updateTokenWith(http, creds, fcmToken)
            override fun isStaleInstallation(exc: Throwable) = Api.isStaleInstallation(exc)
        }, store, tokens, backgroundScope, records, testCommitter(store),
            WorkManagerFcmTokenRetryScheduler { _, policy ->
                policies += policy
                if (policy == ExistingWorkPolicy.REPLACE) activeWorker?.cancel()
            })
        try {
            val worker = async { runFcmTokenSync(repository) }
            activeWorker = worker
            entered.await()
            val first = records.record!!
            tokens.current = "provider-Z"
            val callback = async { repository.onNewFcmToken("provider-Z") }
            runCurrent()
            assertEquals("provider-Z", records.record!!.candidateToken)
            assertEquals(first.incidentId, records.record!!.incidentId)
            assertTrue(records.record!!.generation > first.generation)
            assertTrue(worker.isActive)
            assertEquals(listOf(ExistingWorkPolicy.APPEND_OR_REPLACE), policies)
            release.complete(Unit)
            assertTrue("obsolete terminal result must leave the current work retryable",
                worker.await() is ListenableWorker.Result.Retry)
            callback.await()
            assertEquals(2, updates.size)
            assertTrue(updates.last().contains("provider-Z"))
            assertNull(records.record)
            assertEquals(PushSyncState.Synced, repository.pushState.value)
            assertEquals(DeviceStore.Credentials("valid", "secret"), store.value)
            assertEquals(0, tokens.deletions)
        } finally { release.complete(Unit); http.close() }
    }

    // A cancelled active record is not proof that scheduling remains acknowledged.
    @Test fun cancelled_worker_releases_active_candidate_for_acknowledged_recovery() = runTest {
        val store = WiringCredentials(null)
        val records = TestRecoveryRecords(pending())
        val entered = CompletableDeferred<Unit>()
        val never = CompletableDeferred<Unit>()
        val acknowledge = CompletableDeferred<Unit>()
        var schedulingStarted = false
        var acknowledged = false
        var posts = 0
        val repository = InstallationRepository(object : InstallationApi {
            override suspend fun registerDevice(fcmToken: String): DeviceStore.Credentials {
                posts++
                if (posts == 1) { entered.complete(Unit); never.await() }
                assertTrue("cancelled work needs a fresh scheduling acknowledgement", acknowledged)
                return DeviceStore.Credentials("recovered", "secret")
            }
            override suspend fun updateToken(creds: DeviceStore.Credentials, fcmToken: String) = error("POST only")
            override fun isStaleInstallation(exc: Throwable) = false
        }, store, WiringTokens(), backgroundScope, records, testCommitter(store),
            WorkManagerFcmTokenRetryScheduler { _, policy ->
                assertEquals(ExistingWorkPolicy.APPEND_OR_REPLACE, policy)
                schedulingStarted = true
                acknowledge.await()
                acknowledged = true
            })
        val worker = async { runFcmTokenSync(repository) }
        entered.await()
        worker.cancelAndJoin()
        val durable = records.record!!
        val callback = async { repository.onNewFcmToken("same token") }
        runCurrent()
        assertTrue(schedulingStarted)
        assertEquals(durable, records.record)
        assertEquals(1, posts)
        acknowledge.complete(Unit)
        callback.await()
        assertEquals(2, posts)
        assertEquals(DeviceStore.Credentials("recovered", "secret"), store.value)
        assertNull(records.record)
        assertEquals(PushSyncState.Synced, repository.pushState.value)
    }
}
