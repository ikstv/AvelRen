package ua.avelren.app.data

/**
 * Стан сервера для плашки в шапці. Виведений з трьох реальних сигналів у чисту
 * функцію, щоб його можна було протестувати без Compose/Android і щоб «сервер
 * перезапускається» був ПРАВДИВИМ — приходив із серверного `reboot_required`, а
 * не вгадувався зі свіжості даних (збій зв'язку на телефоні виглядає так само).
 *
 * Пріоритет навмисний:
 *  - немає зв'язку (не можемо дістати сервер) важливіше за все — [OFFLINE];
 *  - сервер САМ повідомив про заплановане оновлення — [RESTARTING] (правда);
 *  - дані застаріли, хоча сервер живий і оновлення нема — окремий чесний
 *    [STALE] («дані застаріли»), а не брехливий «перезапуск»;
 *  - інакше [ONLINE].
 */
enum class ServerState { OFFLINE, RESTARTING, STALE, ONLINE }

fun serverState(
    hasError: Boolean,
    stale: Boolean,
    rebootRequired: Boolean,
): ServerState = when {
    hasError -> ServerState.OFFLINE
    rebootRequired -> ServerState.RESTARTING
    stale -> ServerState.STALE
    else -> ServerState.ONLINE
}
