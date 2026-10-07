package ua.avelren.app.ui

import org.junit.Assert.assertEquals
import org.junit.Test

class EtaTargetPresentationTest {
    private fun badge(iso: String): String {
        val method = Class.forName("ua.avelren.app.ui.AvelRenScreenKt")
            .getDeclaredMethod("etaBadge", String::class.java)
        method.isAccessible = true
        return method.invoke(null, iso) as String
    }

    @Test fun targetKeepsItsDateInsteadOfOnlyTheHour() {
        assertEquals("08.10.2026 о 23:00", badge("2026-10-08T23:00:00+03:00"))
    }

    @Test fun utcTargetUsesKyivDateAcrossMidnight() {
        assertEquals("08.10.2026 о 01:30", badge("2026-10-07T22:30:00Z"))
    }

    @Test fun invalidTargetDoesNotShowRawInput() {
        assertEquals("—", badge("invalid"))
    }

    @Test fun checkpointLabelKeepsTheVehicleQualifier() {
        val method = Class.forName("ua.avelren.app.ui.AvelRenScreenKt")
            .getDeclaredMethod("monitorLabel", String::class.java, String::class.java)
        method.isAccessible = true
        assertEquals("🇵🇱 Ягодин (порожні вантажівки)",
            method.invoke(null, "🇵🇱", "Ягодин (порожні вантажівки)"))
    }
}
