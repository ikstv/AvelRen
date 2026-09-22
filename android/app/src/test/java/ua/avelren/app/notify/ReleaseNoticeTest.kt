package ua.avelren.app.notify

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ReleaseNoticeTest {
    private fun payload(code: String) = mapOf(
        "type" to "health", "subtype" to "app_update", "version_code" to code,
    )

    @Test fun `only a newer version is shown`() {
        assertTrue(shouldShowReleaseNotice(payload("5"), 4))
        assertFalse(shouldShowReleaseNotice(payload("4"), 4))
        assertFalse(shouldShowReleaseNotice(payload("3"), 4))
    }

    @Test fun `invalid or unrelated messages are ignored`() {
        for (code in listOf("", "next", "-1", "2100000001", "99999999999")) {
            assertFalse(shouldShowReleaseNotice(payload(code), 4))
        }
        assertFalse(shouldShowReleaseNotice(mapOf("type" to "health"), 4))
        assertFalse(shouldShowReleaseNotice(payload("5") + ("type" to "threshold"), 4))
    }
}
