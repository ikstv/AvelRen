package ua.avelren.app.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import ua.avelren.app.data.BackgroundDeliveryHint as H

/**
 * The second half of #117: the permission is granted and the push still never
 * arrives, because the system stopped the process first.
 *
 * The tests below care as much about when the hint stays SILENT as about when it
 * appears. A background-delivery warning is shown on a healthy screen to a user
 * who did nothing wrong — if it fires on first launch, or on top of the
 * already-loud "notifications are off" banner, it becomes wallpaper, and the one
 * time it matters nobody reads it.
 */
class BackgroundDeliveryTest {

    private fun eval(
        permissionGranted: Boolean = true,
        ignoringBattery: Boolean = true,
        manufacturer: String? = "Google",
        brand: String? = "google",
        hasSubs: Boolean = true,
        dismissed: Boolean = false,
    ): H = BackgroundDelivery.evaluate(
        permissionGranted = permissionGranted,
        ignoringBatteryOptimizations = ignoringBattery,
        manufacturer = manufacturer,
        brand = brand,
        hasActiveSubscriptions = hasSubs,
        dismissed = dismissed,
    )

    // --- Silence: cases where a warning would do harm ------------------------

    @Test
    fun `stock device with an exemption says nothing`() {
        assertEquals(H.None, eval())
    }

    @Test
    fun `a revoked permission is left to its own louder banner`() {
        // Both problems are real here, but two stacked warnings on one screen
        // get one fix at best. The permission is the blocking one.
        assertEquals(H.None, eval(permissionGranted = false, ignoringBattery = false, manufacturer = "Xiaomi"))
    }

    @Test
    fun `nothing is promised yet, so nothing is warned about`() {
        // A first launch on a Xiaomi with battery optimisation on: every
        // ingredient of the hint is present, but the user asked to be woken
        // about nothing at all.
        assertEquals(H.None, eval(hasSubs = false, ignoringBattery = false, manufacturer = "Xiaomi"))
    }

    @Test
    fun `a dismissed hint stays dismissed`() {
        assertEquals(H.None, eval(dismissed = true, ignoringBattery = false, manufacturer = "Xiaomi"))
    }

    // --- The measured signal ------------------------------------------------

    @Test
    fun `battery optimisation alone is reported as measured`() {
        assertEquals(H.BatteryOptimised, eval(ignoringBattery = false))
    }

    // --- The inferred signal ------------------------------------------------

    @Test
    fun `a MIUI device with an exemption still gets the autostart hint`() {
        // The exemption is real and measured; the autostart list is invisible to
        // every API, so a granted permission plus a battery exemption still does
        // not prove the process will be alive to receive the push.
        assertEquals(H.OemAutostart, eval(manufacturer = "Xiaomi", brand = "Redmi"))
    }

    @Test
    fun `both causes are reported together`() {
        assertEquals(H.BatteryAndAutostart, eval(ignoringBattery = false, manufacturer = "Xiaomi", brand = "POCO"))
    }

    // --- OEM matching -------------------------------------------------------

    @Test
    fun `brand is matched as well as manufacturer`() {
        // POCO devices commonly report MANUFACTURER=Xiaomi, and some Redmi units
        // carry the name on the brand only. Reading one field would miss half of
        // exactly the audience this is for.
        assertTrue(BackgroundDelivery.isAggressiveOem("Xiaomi", "POCO"))
        assertTrue(BackgroundDelivery.isAggressiveOem("unknown", "Redmi"))
        assertTrue(BackgroundDelivery.isAggressiveOem("HUAWEI", null))
    }

    @Test
    fun `matching ignores case and padding`() {
        assertTrue(BackgroundDelivery.isAggressiveOem("  XiaoMi  ", null))
    }

    @Test
    fun `a stock manufacturer is not swept in`() {
        assertFalse(BackgroundDelivery.isAggressiveOem("Google", "google"))
        assertFalse(BackgroundDelivery.isAggressiveOem("samsung", "samsung"))
        assertFalse(BackgroundDelivery.isAggressiveOem(null, null))
    }

    @Test
    fun `a substring of a listed name does not match`() {
        // "vivo" must not make "Vivobook" an aggressive OEM: the list is compared
        // whole, not searched inside, so an unrelated device is not warned at all.
        assertFalse(BackgroundDelivery.isAggressiveOem("Vivobook", "asus"))
    }
}
