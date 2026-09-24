package ua.avelren.app.data

/** Repeated observed loss of internet, not request latency or a server error. */
internal class ConnectionStability {
    private val losses = ArrayDeque<Long>()
    private var lastKnown = InternetState.UNKNOWN

    @Synchronized
    fun observe(state: InternetState, elapsedMs: Long): InternetState {
        while (losses.isNotEmpty() && elapsedMs - losses.first() >= 60_000L) losses.removeFirst()
        if (state == InternetState.OFFLINE &&
            (lastKnown == InternetState.ONLINE || lastKnown == InternetState.WEAK)) {
            losses.addLast(elapsedMs)
        }
        if (state != InternetState.UNKNOWN) lastKnown = state
        return if (state == InternetState.ONLINE && losses.size >= 2) InternetState.WEAK else state
    }
}
