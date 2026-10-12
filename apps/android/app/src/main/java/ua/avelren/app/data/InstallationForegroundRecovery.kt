package ua.avelren.app.data

import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch

/** Process foreground entry for durable push recovery. */
class InstallationForegroundRecovery(
    private val repository: InstallationRepository,
    private val scope: CoroutineScope,
) : DefaultLifecycleObserver {
    override fun onResume(owner: LifecycleOwner) {
        scope.launch { repository.resumePendingTokenSync() }
    }
}
