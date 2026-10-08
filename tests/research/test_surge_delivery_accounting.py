"""Нагадування й повтор HTTP не створюють нових початкових попереджень."""
from datetime import UTC, datetime, timedelta

T = datetime(2026, 10, 2, 10, tzinfo=UTC)


def alert(queue=17):
    return {"alert_id": f"q{queue}", "queue_id": queue, "kind": "surge_forecast",
            "alert_created_at": T, "expires_at": T + timedelta(minutes=30), "closed_at": None}


def test_ack_and_duplicate_do_not_multiply_alerts():
    from tools.surge_experiment.delivery import DeliveryReplay
    delivery = DeliveryReplay()
    value = alert()
    delivery.attach(value)
    delivery.attach(value)
    first = delivery.reserve("q17", T)
    delivery.accept(first["attempt_id"], T)
    assert delivery.reserve("q17", T + timedelta(seconds=299)) is None
    second = delivery.reserve("q17", T + timedelta(seconds=300))
    assert second["ordinal"] == 2
    assert len(delivery.alerts) == 1
    delivery.acknowledge("q17")
    assert delivery.reserve("q17", T + timedelta(seconds=600)) is None


def test_resubscribe_preserves_ack():
    from tools.surge_experiment.delivery import DeliveryReplay
    delivery = DeliveryReplay()
    value = alert()
    delivery.attach(value)
    delivery.acknowledge("q17")
    delivery.unsubscribe(17)
    delivery.attach(value)
    assert delivery.alerts["q17"]["status"] == "acknowledged"


def test_five_queues_cancel_isolated():
    from tools.surge_experiment.delivery import DeliveryReplay
    delivery = DeliveryReplay()
    for queue in (1, 6, 17, 29, 14):
        delivery.attach(alert(queue))
    delivery.acknowledge("q17")
    assert delivery.drain_cancels() == ["q17"]
    assert sum(delivery.reserve(f"q{q}", T) is not None for q in (1, 6, 17, 29, 14)) == 4


def test_unknown_transport_retry_same_attempt():
    from tools.surge_experiment.delivery import DeliveryReplay
    delivery = DeliveryReplay()
    delivery.attach(alert())
    first = dict(delivery.reserve("q17", T))
    assert delivery.reserve("q17", T + timedelta(seconds=59)) is None
    retry = delivery.reserve("q17", T + timedelta(seconds=60))
    assert retry["attempt_id"] == first["attempt_id"]
    assert retry["attempt_count"] == 2
    later = delivery.reserve("q17", T + timedelta(seconds=300))
    assert later["ordinal"] == 2
    assert delivery.attempts[first["attempt_id"]]["abandoned_at"] == T + timedelta(seconds=300)


def test_late_callback_requeues_cancel_but_not_reminder():
    from tools.surge_experiment.delivery import DeliveryReplay
    delivery = DeliveryReplay()
    delivery.attach(alert())
    first = delivery.reserve("q17", T)
    delivery.acknowledge("q17")
    assert delivery.drain_cancels() == ["q17"]
    delivery.accept(first["attempt_id"], T + timedelta(seconds=1))
    assert delivery.drain_cancels() == ["q17"]
    assert delivery.reserve("q17", T + timedelta(minutes=5)) is None
