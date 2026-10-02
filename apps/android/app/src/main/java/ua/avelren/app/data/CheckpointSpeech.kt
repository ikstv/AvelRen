package ua.avelren.app.data

/** Короткі погоджені назви для голосу; категорія береться з актуальної назви черги. */
object CheckpointSpeech {
    private val places = mapOf(
        1 to "на Ягодині",
        2 to "на Ягодині",
        3 to "на Порубному",
        5 to "на Раві-Руській",
        6 to "на Краківці",
        7 to "на Устилузі",
        8 to "на Шегинях",
        9 to "на Дяковому",
        10 to "на Орлівці",
        11 to "на Мамализі",
        12 to "на Виноградівці",
        13 to "на Старокозачому",
        14 to "на Ужгороді",
        15 to "на Рені",
        16 to "на Могилеві-Подільському",
        17 to "на Чопі",
        19 to "на Раві-Руській",
        20 to "на Краківці",
        29 to "на Ягодині",
        31 to "на Угринові",
        79 to "на Лужанці",
        80 to "на Устилузі",
        84 to "на Смільниці",
        85 to "на Малому Березному",
        86 to "на Лужанці",
        88 to "на Грушеві",
        91 to "на Шегинях",
        92 to "на Дяківцях",
        93 to "на КПП «Серпневе один»",
        94 to "на Нових Троянах",
        95 to "на Табаках",
        96 to "на Красноїльську",
        98 to "на Угринові",
        99 to "на Порубному",
        100 to "на Росошанах",
        101 to "на КПП «Малоярославець один»",
        105 to "на Сокирянах",
        107 to "на Маяках-Удобному",
    )
    fun location(id: Int, title: String): String {
        val place = places[id] ?: return "на КПП «$title»"
        val suffix = when {
            title.contains("порожніх", ignoreCase = true) -> " для порожніх вантажівок"
            title.contains("Товари 1-24", ignoreCase = true) -> " для товарів груп від першої до двадцять четвертої"
            title.contains("до ≤ 7,5") -> " для вантажівок від трьох з половиною до семи з половиною тонн"
            title.contains("≤ 3,5") -> " для вантажівок до трьох з половиною тонн"
            title.contains("≤ 7,5") -> " для вантажівок до семи з половиною тонн"
            title.contains("< 7,5") -> " для вантажівок менше семи з половиною тонн"
            else -> ""
        }
        return place + suffix
    }
    fun message(kind: String, id: Int, title: String): String {
        val start = when (kind) {
            "surge_forecast" -> "Можливий початок масової реєстрації"
            "surge_started" -> "Почалось зростання черги"
            else -> throw IllegalArgumentException("Unknown surge kind")
        }
        return "$start ${location(id, title)}"
    }
}
