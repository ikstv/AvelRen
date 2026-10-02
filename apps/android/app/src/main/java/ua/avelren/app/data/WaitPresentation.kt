package ua.avelren.app.data

/** Новий об’єкт є авторитетним; його null ETA не замінюється legacy ETA. */
object WaitPresentation {
    private fun usable(estimate: Api.WaitEstimate): Boolean =
        estimate.seconds != null && when (estimate.status) {
            "reported" -> estimate.seconds >= 0
            "legacy_unknown" -> estimate.seconds > 0
            else -> false
        }

    fun entryEta(workload: Api.Workload): String? = workload.wait_estimate?.let {
        if (usable(it)) it.entry_eta else null
    } ?: if (workload.wait_estimate == null) workload.entry_eta else null

    fun label(estimate: Api.WaitEstimate?): String? {
        if (estimate == null) return null
        if (!usable(estimate)) return "Оцінка очікування відсутня"
        val minutes = estimate.seconds!! / 60
        val days = minutes / 1440
        val hours = minutes % 1440 / 60
        val remainder = minutes % 60
        val duration = when {
            days > 0 -> "$days дн $hours год $remainder хв"
            hours > 0 -> "$hours год $remainder хв"
            else -> "$remainder хв"
        }
        val suffix = if (estimate.status == "legacy_unknown") " · За історичними даними" else ""
        return "$duration очікування$suffix"
    }
}
