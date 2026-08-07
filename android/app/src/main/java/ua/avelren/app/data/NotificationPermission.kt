package ua.avelren.app.data

/**
 * Що саме заважає алерту дійти до користувача (AND-2).
 *
 * Секрет у тому, що «дозвіл на сповіщення» — не один прапорець. Алерт мовчки не
 * з'явиться щонайменше в трьох випадках: немає runtime-permission (Android 13+),
 * сповіщення застосунку вимкнені в системі, або заблокований саме канал
 * `avelren_alerts`. Для сервісу, весь сенс якого — розбудити водія, кожен із них
 * критичний, тож ведемо користувача в потрібне місце, а не показуємо одну
 * загальну помилку.
 */
sealed interface NotificationPermissionState {
    /** Усе гаразд: алерт реально з'явиться. */
    data object Granted : NotificationPermissionState

    /** Можна показати системний діалог запиту. */
    data object NeedsRequest : NotificationPermissionState

    /** Діалог більше не з'явиться — лише налаштування застосунку. */
    data object NeedsAppSettings : NotificationPermissionState

    /** Застосунок дозволений, але канал алертів вимкнений — ведемо в канал. */
    data object NeedsAlertChannelSettings : NotificationPermissionState
}

/**
 * Чиста логіка стану дозволу — без Android-залежностей, тож повністю тестована
 * на JVM. Викликач передає факти (SDK, permission, `areNotificationsEnabled()`,
 * importance каналу, `shouldShowRequestPermissionRationale`) і персистовану
 * історію.
 */
object NotificationPermission {

    /**
     * Персистована історія запитів. Одного `asked` замало: користувач може
     * змахнути діалог, не вибираючи нічого — тоді стан permission не
     * змінюється, і «asked без rationale» помилково виглядав би як permanent
     * denial. Тому явну відмову фіксуємо окремо.
     */
    data class History(
        val asked: Boolean = false,
        val deniedOnce: Boolean = false,
        val everGranted: Boolean = false,
    )

    /** З Android 13 показ сповіщень — runtime-permission POST_NOTIFICATIONS. */
    const val RUNTIME_PERMISSION_SDK = 33

    fun evaluate(
        sdkInt: Int,
        runtimeGranted: Boolean,
        appNotificationsEnabled: Boolean,
        alertChannelBlocked: Boolean,
        showRationale: Boolean,
        history: History,
    ): NotificationPermissionState {
        // 1. Runtime-permission (лише 33+). Без нього решта не має значення.
        if (sdkInt >= RUNTIME_PERMISSION_SDK && !runtimeGranted) {
            return when {
                // Дозвіл був і зник — діалогу вже не буде, тільки Settings.
                history.everGranted -> NotificationPermissionState.NeedsAppSettings
                // Ще не питали, або система готова показати діалог знову.
                !history.asked || showRationale -> NotificationPermissionState.NeedsRequest
                // Явно відмовляли, а rationale вже не пропонують → permanent.
                history.deniedOnce -> NotificationPermissionState.NeedsAppSettings
                // asked, але без явної відмови — це змах діалогу. Не караємо.
                else -> NotificationPermissionState.NeedsRequest
            }
        }

        // 2. Сповіщення застосунку вимкнені в системі. Стосується ВСІХ версій:
        //    на 8–12 runtime-permission немає, і без цієї перевірки застосунок
        //    вважав би, що все гаразд, тоді як пуші йдуть у порожнечу.
        if (!appNotificationsEnabled) return NotificationPermissionState.NeedsAppSettings

        // 3. Застосунок дозволений, але саме канал алертів заблокований
        //    (IMPORTANCE_NONE) — ведемо одразу в налаштування каналу.
        if (alertChannelBlocked) return NotificationPermissionState.NeedsAlertChannelSettings

        return NotificationPermissionState.Granted
    }

    /**
     * Оновлення історії за результатом системного діалогу.
     *
     * `showRationaleNow` читається ПІСЛЯ результату — саме він відрізняє явну
     * відмову (rationale стає true) від змаху діалогу (стан не змінився, тож
     * rationale лишається false).
     */
    fun afterRequest(
        history: History,
        granted: Boolean,
        showRationaleNow: Boolean,
    ): History = history.copy(
        asked = true,
        deniedOnce = history.deniedOnce || (!granted && showRationaleNow),
        everGranted = history.everGranted || granted,
    )
}
