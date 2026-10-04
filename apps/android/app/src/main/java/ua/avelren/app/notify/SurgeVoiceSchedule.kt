package ua.avelren.app.notify

class SurgeVoiceSchedule(startElapsedMs: Long) {
    private val deadline = startElapsedMs + 160_000
    private var nextAt = startElapsedMs
    fun canStart(nowElapsedMs: Long, durationMs: Long): Boolean = durationMs in 1..15_000 &&
        nowElapsedMs >= nextAt && nowElapsedMs <= deadline - durationMs - 1000
    fun reserve(nowElapsedMs: Long, durationMs: Long): Long {
        require(canStart(nowElapsedMs, durationMs))
        nextAt = nowElapsedMs + durationMs + 1000
        return nextAt
    }
}
