package ua.avelren.app.data

/** Local quick-switch preferences, independent from forecasts and monitoring. */
object FavoriteCheckpoints {
    fun parse(stored: String?): List<Int> = stored.orEmpty().split(',')
        .mapNotNull { it.trim().toIntOrNull() }.filter { it > 0 }.distinct()

    fun toggle(current: List<Int>, id: Int): List<Int> {
        val valid = current.filter { it > 0 }.distinct()
        if (id <= 0) return valid
        return if (id in valid) valid.filterNot { it == id } else valid + id
    }

    /** Stable partition: keep every available row, with favorites first. */
    fun <T> orderedForPicker(items: List<T>, favoriteIds: List<Int>, id: (T) -> Int): List<T> {
        val favorites = favoriteIds.filter { it > 0 }.toSet()
        return items.filter { id(it) in favorites } + items.filterNot { id(it) in favorites }
    }
}
