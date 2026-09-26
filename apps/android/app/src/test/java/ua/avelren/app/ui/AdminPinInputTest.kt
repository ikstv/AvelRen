package ua.avelren.app.ui

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class AdminPinInputTest {
    @Test
    fun `only four ASCII digits can be submitted`() {
        assertTrue(isValidAdminPin("7392"))
        for (candidate in listOf("", "7", "739", "73920", "73x2", " 7392", "٧٣٩٢")) {
            assertFalse(candidate, isValidAdminPin(candidate))
        }
    }

    @Test
    fun `input accepts only ASCII digit prefixes of at most four`() {
        assertTrue(isAllowedAdminPinInput(""))
        assertTrue(isAllowedAdminPinInput("73"))
        assertTrue(isAllowedAdminPinInput("7392"))
        for (candidate in listOf("73920", "73x2", "٧", "73 2")) {
            assertFalse(candidate, isAllowedAdminPinInput(candidate))
        }
    }
}
