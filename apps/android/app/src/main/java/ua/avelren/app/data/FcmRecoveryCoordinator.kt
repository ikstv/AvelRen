package ua.avelren.app.data

import java.io.IOException
import java.util.UUID
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.withContext
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import ua.avelren.app.data.DeviceStore.Credentials

class FcmRecoveryCoordinator(
    private val api: RecoveryApi,
    private val credentials: () -> Credentials?,
    private val committer: CredentialCommitter,
    private val records: RecoveryStore,
    private val tokens: RotatingTokenSource,
    private val scheduler: FcmTokenRetryScheduler,
) {
    // operation serializes HTTP/recovery. All durable mutations use gate; a signal
    // releases gate before waiting for operation, so there is no reverse lock order.
    // HTTP does not hold gate: a newer provider handoff can supersede its response.
    private val operation = Mutex()
    private val gate = Mutex()
    private val installation = MutableStateFlow<InstallationState>(InstallationState.Initializing)
    private val push = MutableStateFlow<PushSyncState>(PushSyncState.Pending)
    val state: StateFlow<InstallationState> = installation.asStateFlow()
    val pushState: StateFlow<PushSyncState> = push.asStateFlow()
    private var storageFailed = false
    // Process-local proof of active work, never inferred from a durable phase.
    // gate owns this snapshot; only the serialized operation may advance it.
    private var activeRecord: RecoveryRecord? = null

    suspend fun initialize() = recoverPending(includeMissing = true)

    suspend fun resumePending() = recoverPending(includeMissing = false)

    private suspend fun recoverPending(includeMissing: Boolean) {
        try {
            val pending = gate.withLock {
                checkStorage()
                publishCredentials()
                val existing = records.load()
                when {
                    existing == null -> if (includeMissing) handoffLocked(canonicalToken()) else false
                    existing.phase == RecoveryPhase.CONFLICT_BLOCKED -> handoffLocked(canonicalToken())
                    push.value == PushSyncState.Rejected -> false
                    existing == activeRecord -> false
                    else -> true // restart/failed enqueue still needs scheduling acknowledgement
                }
            }
            if (pending && enqueue()) syncOnce()
        } catch (e: CancellationException) { throw e }
        catch (e: Throwable) { failure(e) }
    }

    /** Callback payloads are deliberately excluded: the SDK's current token is canonical. */
    suspend fun providerSignal() = signal(explicitRetry = false)

    /** Only an explicit user action may retry an unchanged blocked/rejected candidate. */
    suspend fun retryBlocked() = signal(explicitRetry = true)

    private suspend fun signal(explicitRetry: Boolean) {
        try {
            val pending = gate.withLock {
                checkStorage()
                publishCredentials()
                handoffLocked(canonicalToken(), explicitRetry)
            }
            if (pending && enqueue()) syncOnce()
        } catch (e: CancellationException) { throw e }
        catch (e: Throwable) { failure(e) }
    }

    /** Worker entry: continues the durable incident without REPLACE/enqueue of itself. */
    suspend fun syncOnce(): PendingTokenSyncOutcome = operation.withLock {
        try { checkStorage(); syncLocked() }
        catch (e: CancellationException) { throw e }
        catch (e: Throwable) { failure(e) }
    }

    suspend fun <T> authenticatedCall(block: suspend (Credentials) -> T): T {
        if (credentials() == null) initialize()
        val first = credentials() ?: error("installation unavailable")
        try { return block(first) }
        catch (e: CancellationException) { throw e }
        catch (e: Throwable) { if (!api.isStale(e)) throw e }
        operation.withLock {
            try {
                checkStorage()
                val needsRecovery = gate.withLock {
                    if (credentials() != first) false
                    else {
                        commitLocked(first, null)
                        if (records.load() == null) handoffLocked(canonicalToken())
                        true
                    }
                }
                if (needsRecovery) {
                    // A durable record alone cannot prove a prior enqueue was acknowledged.
                    // This external auth path schedules; syncOnce worker recovery never does.
                    if (!enqueue()) error("recovery scheduling unavailable")
                    syncLocked()
                }
            } catch (e: CancellationException) { throw e }
            catch (e: Throwable) { failure(e); throw IllegalStateException("installation recovery unavailable") }
        }
        val fresh = credentials() ?: error("installation unavailable after recovery")
        try { return block(fresh) }
        catch (e: CancellationException) { throw e }
        catch (e: Throwable) {
            if (api.isStale(e)) gate.withLock {
                if (credentials() == fresh) commitLocked(fresh, null)
            }
            throw e
        }
    }

    private suspend fun syncLocked(): PendingTokenSyncOutcome = try {
        syncActive()
    } finally {
        withContext(NonCancellable) { gate.withLock { activeRecord = null } }
    }

    private suspend fun syncActive(): PendingTokenSyncOutcome {
        while (true) {
            var record = gate.withLock {
                checkStorage()
                records.load().also { activeRecord = it }
            }
                ?: return PendingTokenSyncOutcome.NothingPending
            if (record.phase == RecoveryPhase.CONFLICT_BLOCKED) {
                push.value = PushSyncState.ConflictBlocked
                return PendingTokenSyncOutcome.TerminalFailure(IllegalStateException("push conflict blocked"))
            }
            if (push.value == PushSyncState.Rejected) {
                return PendingTokenSyncOutcome.TerminalFailure(IllegalStateException("push sync rejected"))
            }
            if (record.phase == RecoveryPhase.ROTATION_REQUESTED) {
                // A timeout may have deleted X already. Observe Y before any repeat delete.
                val current = canonicalToken()
                if (current != record.rotationSourceToken) {
                    record = transition(record, record.next(
                        phase = RecoveryPhase.ROTATED, candidate = current, rotations = 1,
                        generation = increment(record.generation),
                    )) ?: return superseded()
                } else {
                    // Confirm this precise request is still current before the SDK mutation.
                    val rotated = gate.withLock {
                        if (records.load() != record) null else {
                            provider { tokens.deleteCurrentToken() }
                            transitionLocked(record, record.next(
                                phase = RecoveryPhase.ROTATED, candidate = null, rotations = 1,
                            ))
                        }
                    }
                    record = rotated ?: return superseded()
                }
            }
            if (record.phase == RecoveryPhase.ROTATED) {
                val current = canonicalToken()
                if (current == record.rotationSourceToken) return retry()
                record = transition(record, record.next(
                    phase = RecoveryPhase.ATTACHING, candidate = current,
                    generation = if (record.candidateToken == current) record.generation else increment(record.generation),
                )) ?: return superseded()
            } else {
                val current = canonicalToken()
                record = transition(record, record.next(
                    phase = RecoveryPhase.ATTACHING, candidate = current,
                    generation = if (record.candidateToken == current) record.generation else increment(record.generation),
                )) ?: return superseded()
            }
            val used = gate.withLock {
                if (records.load() != record) return superseded()
                credentials()
            }
            try {
                if (used == null) {
                    val fresh = api.register(record.candidateToken!!)
                    val accepted = gate.withLock {
                        if (records.load() != record) false else {
                            commitLocked(null, fresh)
                            transitionLocked(record, null) != null
                        }
                    }
                    if (!accepted) return superseded()
                } else {
                    api.update(used, record.candidateToken!!)
                    val accepted = gate.withLock {
                        if (records.load() != record || credentials() != used) false
                        else {
                            publishCredentials()
                            transitionLocked(record, null) != null
                        }
                    }
                    if (!accepted) return superseded()
                }
                return PendingTokenSyncOutcome.Synced
            } catch (e: CancellationException) { throw e }
            catch (e: Throwable) {
                if (e is RecoveryStorageException) throw e
                if (api.isStale(e) && used != null) {
                    val cleared = gate.withLock {
                        if (records.load() != record || credentials() != used) false
                        else { commitLocked(used, null); true }
                    }
                    if (!cleared) return superseded()
                    // Only one POST recovery follows a confirmed stale pair. The next
                    // iteration sees no credentials and cannot loop on another PUT401.
                } else if (api.isTokenConflict(e)) {
                    val next = if (record.completedRotations == 1) record.next(phase = RecoveryPhase.CONFLICT_BLOCKED)
                    else record.next(phase = RecoveryPhase.ROTATION_REQUESTED, source = record.candidateToken)
                    if (transition(record, next) == null) return superseded()
                } else return gate.withLock {
                    // An obsolete terminal response must not fail the successor chain
                    // or overwrite the status of a genuinely newer candidate.
                    if (records.load() != record) superseded() else failure(e)
                }
            }
        }
    }

    private suspend fun handoffLocked(token: String, explicitRetry: Boolean = false): Boolean {
        if (token.isBlank()) throw IOException("push token unavailable")
        val current = records.load()
        if (current?.phase == RecoveryPhase.CONFLICT_BLOCKED && current.candidateToken == token && !explicitRetry) {
            push.value = PushSyncState.ConflictBlocked
            return false
        }
        if (current?.candidateToken == token && push.value == PushSyncState.Rejected && !explicitRetry) return false
        val next = if (current == null) RecoveryRecord(
            1, 1, UUID.randomUUID().toString(), 1, RecoveryPhase.PENDING, token, null, 0,
        ) else if (current.phase == RecoveryPhase.ROTATION_REQUESTED) {
            if (current.rotationSourceToken == token) current
            else current.next(phase = RecoveryPhase.ROTATED, candidate = token, rotations = 1,
                generation = increment(current.generation))
        } else if (current.phase == RecoveryPhase.ROTATED && token == current.rotationSourceToken) current
        else if (current.candidateToken == token && current.phase != RecoveryPhase.CONFLICT_BLOCKED) current
        else current.next(phase = RecoveryPhase.PENDING, candidate = token,
            generation = if (current.candidateToken == token) current.generation else increment(current.generation))
        if (next != current && !records.compareAndSet(current, next)) throw RecoveryStorageException()
        // Same canonical callback cannot invalidate an HTTP result or schedule a successor
        // for its own active worker. An inactive durable record still needs enqueue.
        if (next == current && next == activeRecord) return false
        push.value = PushSyncState.Pending
        return true
    }

    // A non-null return acknowledges either the replacement or successful clear.
    private suspend fun transitionLocked(expected: RecoveryRecord, replacement: RecoveryRecord?): RecoveryRecord? {
        checkStorage()
        if (records.load() != expected) return null
        if (!records.compareAndSet(expected, replacement)) {
            if (records.load() != expected) return null
            throw RecoveryStorageException()
        }
        if (activeRecord == expected) activeRecord = replacement
        if (replacement == null) push.value = PushSyncState.Synced
        return replacement ?: expected
    }

    private suspend fun transition(expected: RecoveryRecord, replacement: RecoveryRecord?) =
        gate.withLock { transitionLocked(expected, replacement) }

    private suspend fun commitLocked(expected: Credentials?, replacement: Credentials?) {
        if (!committer.commit(expected, replacement)) throw RecoveryStorageException()
        publishCredentials()
    }

    private fun publishCredentials() {
        installation.value = credentials()?.let { InstallationState.Ready(it.deviceId) }
            ?: InstallationState.Unavailable("installation unavailable")
    }

    private suspend fun enqueue(): Boolean = when (scheduler.enqueue()) {
        ScheduleResult.Enqueued -> true
        is ScheduleResult.Failed -> gate.withLock {
            checkStorage()
            // Another signal can finish while this enqueue is awaiting acknowledgement.
            push.value = when (records.load()?.phase) {
                null -> PushSyncState.Synced
                RecoveryPhase.CONFLICT_BLOCKED -> PushSyncState.ConflictBlocked
                else -> PushSyncState.Retrying
            }
            false
        }
    }

    private suspend fun canonicalToken(): String = provider { tokens.currentToken() }.also {
        if (it.isBlank()) throw IOException("push provider unavailable")
    }

    private suspend fun <T> provider(block: suspend () -> T): T = try { block() }
    catch (e: CancellationException) { throw e }
    catch (_: Throwable) { throw IOException("push provider unavailable") }

    private fun checkStorage() { if (storageFailed) throw RecoveryStorageException() }
    private fun retry(): PendingTokenSyncOutcome {
        push.value = PushSyncState.Retrying
        return PendingTokenSyncOutcome.RetryableFailure(IOException("push sync pending"))
    }
    private fun superseded() = retry()
    private fun failure(error: Throwable): PendingTokenSyncOutcome {
        if (error is CancellationException) throw error
        if (error is RecoveryStorageException) {
            storageFailed = true
            push.value = PushSyncState.StorageFailed
            return PendingTokenSyncOutcome.RetryableFailure(RecoveryStorageException())
        }
        val classified = classifyTokenSyncFailure(error)
        // Public status/errors carry categories, never SDK/HTTP diagnostic strings.
        return if (classified is PendingTokenSyncOutcome.RetryableFailure) retry()
        else {
            push.value = PushSyncState.Rejected
            PendingTokenSyncOutcome.TerminalFailure(IllegalStateException("push sync rejected"))
        }
    }

    private fun increment(value: Long): Long {
        if (value == Long.MAX_VALUE) throw RecoveryStorageException()
        return value + 1
    }

    private fun RecoveryRecord.next(
        phase: RecoveryPhase = this.phase,
        candidate: String? = candidateToken,
        source: String? = rotationSourceToken,
        rotations: Int = completedRotations,
        generation: Long = this.generation,
    ) = copy(revision = increment(revision), generation = generation, phase = phase,
        candidateToken = candidate, rotationSourceToken = source, completedRotations = rotations)
}
