package ua.avelren.app.ui

internal fun isAllowedAdminPinInput(value: String): Boolean =
    value.length <= 4 && value.all { it in '0'..'9' }

internal fun isValidAdminPin(value: String): Boolean =
    value.length == 4 && isAllowedAdminPinInput(value)
