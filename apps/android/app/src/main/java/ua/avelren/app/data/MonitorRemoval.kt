package ua.avelren.app.data

/** Reconcile only after the server has confirmed removal of the monitor. */
internal suspend fun removeMonitorAndReconcile(
    remove: suspend () -> Unit,
    reconcile: suspend () -> Unit,
) {
    remove()
    reconcile()
}
