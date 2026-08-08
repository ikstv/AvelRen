package ua.avelren.app.data

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.await
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.CancellationException
import io.ktor.client.plugins.ClientRequestException
import io.ktor.client.plugins.HttpRequestTimeoutException
import io.ktor.client.plugins.ServerResponseException

interface PendingFcmTokenStore {
    fun load(): String?
    fun save(token: String): Boolean
    fun clearIfMatches(expectedToken: String): Boolean
}

class DevicePendingFcmTokenStore(private val context: Context) : PendingFcmTokenStore {
    override fun load(): String? = DeviceStore.pendingFcmToken(context)
    override fun save(token: String): Boolean = DeviceStore.savePendingFcmToken(context, token)
    override fun clearIfMatches(expectedToken: String): Boolean =
        DeviceStore.clearPendingFcmTokenIfMatches(context, expectedToken)
}

sealed interface ScheduleResult {
    data object Enqueued : ScheduleResult
    data class Failed(val cause: Throwable) : ScheduleResult
}

interface FcmTokenRetryScheduler {
    suspend fun enqueue(): ScheduleResult
}

class WorkManagerFcmTokenRetryScheduler(context: Context) : FcmTokenRetryScheduler {
    private val workManager = WorkManager.getInstance(context.applicationContext)

    override suspend fun enqueue(): ScheduleResult = try {
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()
        val request = OneTimeWorkRequestBuilder<FcmTokenSyncWorker>()
            .setConstraints(constraints)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .build()
        workManager.enqueueUniqueWork(
            FcmTokenSyncWorker.UNIQUE_WORK_NAME,
            ExistingWorkPolicy.REPLACE,
            request,
        ).await()
        ScheduleResult.Enqueued
    } catch (e: CancellationException) {
        throw e
    } catch (e: Throwable) {
        ScheduleResult.Failed(e)
    }
}

class InMemoryPendingFcmTokenStore : PendingFcmTokenStore {
    private var token: String? = null
    override fun load(): String? = token
    override fun save(token: String): Boolean { this.token = token; return true }
    override fun clearIfMatches(expectedToken: String): Boolean {
        if (token != expectedToken) return false
        token = null
        return true
    }
}

class ImmediateFcmTokenRetryScheduler : FcmTokenRetryScheduler {
    override suspend fun enqueue(): ScheduleResult = ScheduleResult.Enqueued
}

sealed interface PendingTokenSyncOutcome {
    data object NothingPending : PendingTokenSyncOutcome
    data object Synced : PendingTokenSyncOutcome
    data class RetryableFailure(val cause: Throwable) : PendingTokenSyncOutcome
    data class TerminalFailure(val cause: Throwable) : PendingTokenSyncOutcome
}

fun classifyTokenSyncFailure(error: Throwable): PendingTokenSyncOutcome = when (error) {
    is CancellationException -> throw error
    is HttpRequestTimeoutException, is IOException -> PendingTokenSyncOutcome.RetryableFailure(error)
    is ServerResponseException -> PendingTokenSyncOutcome.RetryableFailure(error)
    is ClientRequestException -> when (error.response.status.value) {
        408, 429 -> PendingTokenSyncOutcome.RetryableFailure(error)
        else -> PendingTokenSyncOutcome.TerminalFailure(error)
    }
    else -> PendingTokenSyncOutcome.TerminalFailure(error)
}
