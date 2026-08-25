package ua.avelren.app.data

import org.junit.Assert.assertEquals
import org.junit.Test

class ServerStateTest {
    @Test fun online_when_all_clear() =
        assertEquals(ServerState.ONLINE, serverState(hasError = false, stale = false, rebootRequired = false))

    @Test fun restarting_only_from_real_server_signal() =
        assertEquals(ServerState.RESTARTING, serverState(hasError = false, stale = false, rebootRequired = true))

    @Test fun stale_data_is_not_restarting() =
        assertEquals(ServerState.STALE, serverState(hasError = false, stale = true, rebootRequired = false))

    @Test fun no_connection_wins_over_everything() {
        // Під час реального ребуту сервер недосяжний → показуємо OFFLINE, а не
        // «перезапуск», бо телефон однаково не може підтвердити стан наживо.
        assertEquals(ServerState.OFFLINE, serverState(hasError = true, stale = true, rebootRequired = true))
    }

    @Test fun reboot_takes_priority_over_stale() =
        assertEquals(ServerState.RESTARTING, serverState(hasError = false, stale = true, rebootRequired = true))
}
