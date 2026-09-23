package ua.avelren.app.data

import com.google.android.play.core.install.model.InstallStatus

enum class PlayUpdateState {
    NONE, AVAILABLE, DOWNLOADING, READY, INSTALLING;

    val actionable: Boolean get() = this == AVAILABLE || this == READY
}

internal fun playUpdateState(installStatus: Int, available: Boolean): PlayUpdateState =
    when (installStatus) {
        InstallStatus.DOWNLOADED -> PlayUpdateState.READY
        InstallStatus.PENDING, InstallStatus.DOWNLOADING -> PlayUpdateState.DOWNLOADING
        InstallStatus.INSTALLING -> PlayUpdateState.INSTALLING
        InstallStatus.INSTALLED -> PlayUpdateState.NONE
        else -> if (available) PlayUpdateState.AVAILABLE else PlayUpdateState.NONE
    }
