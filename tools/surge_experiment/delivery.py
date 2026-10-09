"""Локальний облік одного синтетичного підписника без мережевої доставки."""
from datetime import timedelta


class DeliveryReplay:
    def __init__(self):
        self.alerts, self.attempts, self.latest = {}, {}, {}
        self.pending_cancels = set()
        self.cancelled = set()
        self.disabled = set()
        self.bindings, self.generations = {}, {}

    def attach(self, event):
        source = event["alert_id"]
        key = self.bindings.get(source)
        if key in self.alerts:
            return key
        if event["queue_id"] in self.disabled:
            return None
        return self._attach(event, event["alert_created_at"])

    def _attach(self, event, now):
        source = event["alert_id"]
        generation = self.generations.get(source, 0)
        key = source if generation == 0 else f"{source}:subscription:{generation}"
        self.generations[source] = generation + 1
        self.bindings[source] = key
        self.alerts[key] = {"event": event, "status": "pending", "created_at": now,
                            "next_attempt_at": now}
        return key

    def subscribe(self, event, now):
        """Explicit user join; worker attach only refreshes the existing binding."""
        self.disabled.discard(event["queue_id"])
        key = self.bindings.get(event["alert_id"])
        if key in self.alerts:
            if self.alerts[key]["status"] != "expired":
                return key  # ACK survives re-enabling the same active episode.
            del self.alerts[key]
        if event["closed_at"] is not None or event["expires_at"] <= now:
            return None
        return self._attach(event, now)

    def acknowledge(self, key):
        alert = self.alerts.get(key)
        if alert is not None:
            alert["status"] = "acknowledged"
            self._cancel(key)

    def _cancel(self, key, force=False):
        if force or key not in self.cancelled:
            self.pending_cancels.add(key)
            self.cancelled.add(key)

    def unsubscribe(self, queue_id):
        self.disabled.add(queue_id)
        for key, alert in self.alerts.items():
            if alert["event"]["queue_id"] == queue_id and alert["status"] == "pending":
                alert["status"] = "expired"
                self._cancel(key)

    def expire(self, now):
        for key, alert in self.alerts.items():
            if alert["status"] == "pending" and not self._active(alert, now):
                alert["status"] = "expired"
                self._cancel(key)

    @staticmethod
    def _active(alert, now):
        event = alert["event"]
        return event["closed_at"] is None and event["expires_at"] > now

    def reserve(self, key, now):
        alert = self.alerts.get(key)
        if alert is None:
            return None
        if (alert["status"] != "pending" or not self._active(alert, now)
                or int((alert["event"]["expires_at"] - now).total_seconds()) <= 0):
            return None
        last = self.latest.get(key)
        if last and last["accepted_at"] is None and last["abandoned_at"] is None:
            if now < last["created_at"] + timedelta(seconds=300):
                if now - last["last_attempt_at"] < timedelta(seconds=60):
                    return None
                last["last_attempt_at"] = now
                last["attempt_count"] += 1
                return dict(last)
            last["abandoned_at"] = now
        elif now < alert["next_attempt_at"]:
            return None
        ordinal = last["ordinal"] + 1 if last else 1
        attempt_id = f"{key}:attempt:{ordinal}"
        attempt = {"alert_id": key, "attempt_id": attempt_id, "ordinal": ordinal,
                   "source_event_id": alert["event"]["alert_id"],
                   "queue_id": alert["event"]["queue_id"],
                   "created_at": now, "last_attempt_at": now, "attempt_count": 1,
                   "accepted_at": None, "abandoned_at": None}
        self.attempts[attempt_id] = self.latest[key] = attempt
        alert["next_attempt_at"] = now + timedelta(seconds=300)
        return dict(attempt)

    def accept(self, attempt_id, now):
        attempt = self.attempts[attempt_id]
        attempt.update(accepted_at=now, abandoned_at=None)
        key = attempt["alert_id"]
        alert = self.alerts.get(key)
        if alert is None:
            self._cancel(key, force=True)
            return
        if alert["status"] == "pending" and self._active(alert, now):
            if self.latest[key]["ordinal"] == attempt["ordinal"]:
                alert["next_attempt_at"] = now + timedelta(seconds=300)
            return
        if alert["status"] == "pending":
            alert["status"] = "expired"
        self._cancel(key, force=True)

    def drain_cancels(self):
        result = sorted(self.pending_cancels)
        self.pending_cancels.clear()
        return result
