package ua.avelren.app.data

import com.google.android.play.core.install.model.InstallStatus
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class PlayUpdateStateTest {
    @Test fun downloadedIsReadyEvenWithoutAnotherAvailableUpdate() {
        assertEquals(PlayUpdateState.READY, playUpdateState(InstallStatus.DOWNLOADED, false))
        assertTrue(PlayUpdateState.READY.actionable)
    }

    @Test fun downloadCannotBeStartedTwice() {
        for (status in listOf(InstallStatus.PENDING, InstallStatus.DOWNLOADING)) {
            val state = playUpdateState(status, true)
            assertEquals(PlayUpdateState.DOWNLOADING, state)
            assertFalse(state.actionable)
        }
    }

    @Test fun installingCannotBeCompletedTwice() {
        assertEquals(PlayUpdateState.INSTALLING, playUpdateState(InstallStatus.INSTALLING, true))
        assertFalse(PlayUpdateState.INSTALLING.actionable)
    }

    @Test fun installedRemovesReminder() {
        assertEquals(PlayUpdateState.NONE, playUpdateState(InstallStatus.INSTALLED, true))
    }

    @Test fun canceledOrFailedCanRetryIfPlayStillOffersUpdate() {
        for (status in listOf(InstallStatus.CANCELED, InstallStatus.FAILED, InstallStatus.UNKNOWN)) {
            assertEquals(PlayUpdateState.AVAILABLE, playUpdateState(status, true))
            assertEquals(PlayUpdateState.NONE, playUpdateState(status, false))
        }
        assertTrue(PlayUpdateState.AVAILABLE.actionable)
        assertFalse(PlayUpdateState.NONE.actionable)
    }
}
