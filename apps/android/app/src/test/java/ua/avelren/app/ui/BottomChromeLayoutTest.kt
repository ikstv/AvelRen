package ua.avelren.app.ui

import org.junit.Assert.assertEquals
import org.junit.Test

class BottomChromeLayoutTest {
    @Test fun unmeasuredChromeKeepsSafeInitialInset() {
        assertEquals(136f, bottomChromeContentInset(0f, false), 0.01f)
        assertEquals(182f, bottomChromeContentInset(0f, true), 0.01f)
    }

    @Test fun largeTextReservesAllMeasuredChromeAndContentGap() {
        assertEquals(292f, bottomChromeContentInset(280f, false), 0.01f)
        assertEquals(342f, bottomChromeContentInset(330f, true), 0.01f)
    }

    @Test fun insetShrinksWhenFontOrFooterReturnsToNormal() {
        assertEquals(252f, bottomChromeContentInset(240f, false), 0.01f)
        assertEquals(136f, bottomChromeContentInset(100f, false), 0.01f)
    }
}
