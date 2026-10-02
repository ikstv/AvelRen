package ua.avelren.app.data

class SurgeRepository(private val installation: InstallationRepository, private val api: SurgeApi = SurgeApi()) {
    suspend fun checkpoints(): List<SurgeCheckpoint> = api.checkpoints()
    suspend fun snapshot(checkpointId: Int): SurgeStatus = api.snapshot(checkpointId)
    suspend fun subscriptions(): List<SurgeSubscription> = installation.authenticatedCall { api.subscriptions(it) }
    suspend fun setSubscription(checkpointId: Int, forecast: Boolean, fact: Boolean) =
        installation.authenticatedCall { api.setSubscription(it, checkpointId, forecast, fact) }
    suspend fun removeSubscription(checkpointId: Int) =
        installation.authenticatedCall { api.removeSubscription(it, checkpointId) }
    suspend fun ack(alertId: Long) = installation.authenticatedCall { api.ack(it, alertId) }
}
