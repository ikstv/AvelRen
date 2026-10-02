package ua.avelren.app.data

interface SurgeMonitorClient {
    suspend fun checkpoints(): List<SurgeCheckpoint>
    suspend fun snapshot(checkpointId: Int): SurgeStatus
    suspend fun subscriptions(): List<SurgeSubscription>
    suspend fun setSubscription(checkpointId: Int, forecast: Boolean, fact: Boolean)
    suspend fun removeSubscription(checkpointId: Int)
}

class SurgeRepository(private val installation: InstallationRepository, private val api: SurgeApi = SurgeApi()) : SurgeMonitorClient {
    override suspend fun checkpoints(): List<SurgeCheckpoint> = api.checkpoints()
    override suspend fun snapshot(checkpointId: Int): SurgeStatus = api.snapshot(checkpointId)
    override suspend fun subscriptions(): List<SurgeSubscription> = installation.authenticatedCall { api.subscriptions(it) }
    override suspend fun setSubscription(checkpointId: Int, forecast: Boolean, fact: Boolean) =
        installation.authenticatedCall { api.setSubscription(it, checkpointId, forecast, fact) }
    override suspend fun removeSubscription(checkpointId: Int) =
        installation.authenticatedCall { api.removeSubscription(it, checkpointId) }
    suspend fun ack(alertId: Long) = installation.authenticatedCall { api.ack(it, alertId) }
}
