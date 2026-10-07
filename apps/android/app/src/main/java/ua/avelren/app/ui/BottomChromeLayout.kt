package ua.avelren.app.ui

/** Нижній резерв вмісту; висоти передаються в dp, без системних inset. */
internal fun bottomChromeContentInset(measuredHeightDp: Float, updateAvailable: Boolean): Float =
    maxOf(if (updateAvailable) 182f else 136f, measuredHeightDp + 12f)
