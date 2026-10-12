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

sealed interface ScheduleResult {
    data object Enqueued : ScheduleResult
    data class Failed(val cause: Throwable) : ScheduleResult
}

interface FcmTokenRetryScheduler {
    suspend fun enqueue(): ScheduleResult
}

class WorkManagerFcmTokenRetryScheduler internal constructor(
    private val enqueueWork: suspend (String, ExistingWorkPolicy) -> Unit,
) : FcmTokenRetryScheduler {
    constructor(context: Context) : this({ name, policy ->
        val workManager = WorkManager.getInstance(context.applicationContext)
        val constraints = Constraints.Builder()
            .setRequiredNetworkType(NetworkType.CONNECTED)
            .build()
        val request = OneTimeWorkRequestBuilder<FcmTokenSyncWorker>()
            .setConstraints(constraints)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .build()
        workManager.enqueueUniqueWork(name, policy, request).await()
        Unit
    })

    override suspend fun enqueue(): ScheduleResult = try {
        // A genuinely newer candidate gets a successor even if the current worker
        // finishes terminally. Failed/cancelled chains restart, running HTTP survives.
        enqueueWork(FcmTokenSyncWorker.UNIQUE_WORK_NAME, ExistingWorkPolicy.APPEND_OR_REPLACE)
        ScheduleResult.Enqueued
    } catch (e: CancellationException) {
        throw e
    } catch (e: Throwable) {
        ScheduleResult.Failed(e)
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
