package ua.avelren.app.data

/**
 * Why a *granted* notification permission still may not wake the driver (#117).
 *
 * [NotificationPermission] answers "is the app allowed to show an alert". This
 * answers the next question, which is the one that actually bites on the phones
 * our drivers carry: the app is allowed, and the push still never arrives,
 * because the system stopped the process before FCM could deliver it.
 *
 * Two causes, and they are NOT the same kind of fact:
 *
 *  - **Battery optimisation** is measurable. `PowerManager.isIgnoringBatteryOptimizations`
 *    is a real API returning a real answer about this installation.
 *  - **OEM autostart lists** (MIUI and its relatives) are not exposed by any API.
 *    Nothing can read them, so the only available signal is the manufacturer —
 *    a guess about a device class, not a fact about this device.
 *
 * The distinction is kept all the way into the wording shown to the user: we say
 * "turn this off" about the thing we measured, and "check this" about the thing
 * we inferred. Presenting a guess as a measurement is how a helpful hint turns
 * into a false alarm that teaches people to ignore the next one.
 */
sealed interface BackgroundDeliveryHint {
    /** Nothing to say — either all is well, or a louder problem already has the screen. */
    data object None : BackgroundDeliveryHint

    /** Measured: this installation is subject to Doze / battery optimisation. */
    data object BatteryOptimised : BackgroundDeliveryHint

    /** Inferred from the manufacturer: an autostart list no API can read. */
    data object OemAutostart : BackgroundDeliveryHint

    /** Both of the above. */
    data object BatteryAndAutostart : BackgroundDeliveryHint
}

object BackgroundDelivery {

    /**
     * Manufacturers whose stock firmware kills background delivery beyond what
     * Doze does, through an autostart/"protected apps" list that no public API
     * exposes.
     *
     * Xiaomi is the reason this exists — among Ukrainian truck drivers it is a
     * typical phone, not an exotic one — but the same firmware family ships as
     * Redmi and POCO, and the other names here behave the same way. Matching is
     * done on both manufacturer and brand because these two disagree often
     * enough to matter: a POCO device commonly reports MANUFACTURER=Xiaomi,
     * while some Redmi units report the brand only.
     */
    val AGGRESSIVE_OEMS: Set<String> = setOf(
        "xiaomi", "redmi", "poco",
        "huawei", "honor",
        "oppo", "realme", "oneplus", "vivo", "iqoo",
        "meizu", "zte", "tecno", "infinix",
    )

    fun isAggressiveOem(manufacturer: String?, brand: String?): Boolean =
        listOfNotNull(manufacturer, brand)
            .any { it.trim().lowercase() in AGGRESSIVE_OEMS }

    /**
     * @param permissionGranted   result of [NotificationPermission.evaluate] being Granted.
     * @param ignoringBatteryOptimizations measured via PowerManager for this package.
     * @param hasActiveSubscriptions whether the user asked to be woken about anything.
     * @param dismissed           the user has already read this hint and closed it.
     */
    fun evaluate(
        permissionGranted: Boolean,
        ignoringBatteryOptimizations: Boolean,
        manufacturer: String?,
        brand: String?,
        hasActiveSubscriptions: Boolean,
        dismissed: Boolean,
    ): BackgroundDeliveryHint {
        // A revoked permission is the bigger and louder problem, and it already
        // owns a banner. Two warnings stacked on one screen read as noise, and
        // the user fixes neither.
        if (!permissionGranted) return BackgroundDeliveryHint.None

        // Nothing is expected to arrive yet. Warning a first-time user about
        // undelivered alerts they never asked for is how a real warning gets
        // trained into wallpaper.
        if (!hasActiveSubscriptions) return BackgroundDeliveryHint.None

        if (dismissed) return BackgroundDeliveryHint.None

        val battery = !ignoringBatteryOptimizations
        val oem = isAggressiveOem(manufacturer, brand)

        return when {
            battery && oem -> BackgroundDeliveryHint.BatteryAndAutostart
            battery -> BackgroundDeliveryHint.BatteryOptimised
            oem -> BackgroundDeliveryHint.OemAutostart
            else -> BackgroundDeliveryHint.None
        }
    }
}
