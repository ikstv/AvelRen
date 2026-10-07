package ua.avelren.app.data

/** Локальний вибір для погодження UI; це не серверні підписки. */
object ForecastSelection {
    const val MAX = 3
    fun parse(value: String?): List<Int> = value.orEmpty().split(',')
        .mapNotNull { it.toIntOrNull()?.takeIf { id -> id > 0 } }.distinct().take(MAX)
    fun add(current: List<Int>, id: Int): List<Int> =
        if (id <= 0 || id in current || current.size >= MAX) current else current + id
    fun remove(current: List<Int>, id: Int): List<Int> = current.filterNot { it == id }
}
