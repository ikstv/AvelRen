"""Local operator control only; no server endpoint or credentials."""

from types import SimpleNamespace

from avelren import collector_control
from avelren.collector_spool import SpoolStatus


def test_control_times_out_after_30_seconds(monkeypatch):
    calls = []
    clock = SimpleNamespace(value=0.0)

    class Store:
        def __init__(self, path):
            assert path == collector_control.SPOOL_PATH

        def set_capture_only(self, enabled):
            calls.append(enabled)

        def status(self):
            return SimpleNamespace(mode_ack=None, capture_only=True)

        def close(self):
            pass

    monkeypatch.setattr(collector_control, "SpoolStore", Store)
    monkeypatch.setattr(collector_control.time, "monotonic", lambda: clock.value)
    def advance(seconds):
        clock.value += seconds

    monkeypatch.setattr(collector_control.time, "sleep", advance)
    assert collector_control.main(["capture-only", "on"]) == 1
    assert calls == [True]
    assert clock.value >= 30


def test_control_status_does_not_change_mode(monkeypatch):
    calls = []

    class Store:
        def __init__(self, path):
            assert path == collector_control.SPOOL_PATH

        def set_capture_only(self, enabled):
            calls.append(enabled)

        def status(self):
            return SpoolStatus(
                pending_count=2, oldest_pending_at=None, capture_only=True,
                mode_ack=True, last_error=None, max_cycle_bytes=100, acked_count=0,
                spool_bytes=4096,
            )

        def close(self):
            pass

    monkeypatch.setattr(collector_control, "SpoolStore", Store)
    assert collector_control.main(["capture-only", "status"]) == 0
    assert calls == []
