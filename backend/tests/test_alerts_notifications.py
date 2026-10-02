from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest

from app.alerts.facade import AlertFacade
from app.alerts.notifications import AlertNotificationBroker, BrowserOwnedAlertChannel
from app.core.executors import run_storage


def test_browser_owned_channel_publishes_to_active_subscriber() -> None:
    async def _run() -> None:
        broker = AlertNotificationBroker(queue_size=2)
        subscription = broker.subscribe()
        channel = BrowserOwnedAlertChannel("in_app", broker)

        outcome = await channel.dispatch(
            {
                "id": "event-1",
                "ruleId": "rule-1",
                "message": "hit",
                "target": {"symbol": "BTCUSDT"},
                "values": {"close": 1},
                "createdAt": 1,
            },
            {"type": "in_app", "enabled": True, "config": {}},
        )
        await asyncio.sleep(0)
        delivered = subscription.queue.get_nowait()

        assert outcome["status"] == "published"
        assert outcome["subscriberCount"] == 1
        assert delivered["dispatchId"] == outcome["dispatchId"]
        assert delivered["action"]["type"] == "in_app"
        broker.unsubscribe(subscription)
        assert broker.snapshot()["subscribers"] == 0

    asyncio.run(_run())


def test_notification_broker_is_bounded_and_reports_drops() -> None:
    broker = AlertNotificationBroker(queue_size=1)
    subscription = broker.subscribe()

    broker.publish({"dispatchId": "first"})
    broker.publish({"dispatchId": "second"})

    assert subscription.queue.qsize() == 1
    assert subscription.queue.get_nowait()["dispatchId"] == "second"
    assert broker.snapshot()["dropped"] == 1


def test_facade_persists_dispatch_before_client_receives_event(tmp_path: Path) -> None:
    async def _run() -> None:
        facade = AlertFacade(store_path=tmp_path / "alerts.json")
        rule = facade.save_rule({
            "name": "probe",
            "target": {
                "exchange": "binance",
                "marketType": "spot",
                "symbol": "BTCUSDT",
                "interval": "1m",
            },
            "expression": {
                "left": "close",
                "comparator": ">",
                "right": {"type": "number", "value": 1},
            },
            "actions": [{"type": "in_app", "enabled": True, "config": {}}],
            "maxTriggers": 1,
        })
        subscription = facade.notification_broker.subscribe()

        event = await facade.emit_triggered({
            "ruleId": rule["id"],
            "message": "hit",
            "values": {"close": 2},
        })
        await asyncio.sleep(0)
        notification = subscription.queue.get_nowait()
        persisted = facade.list_history(rule_id=rule["id"])[0]

        assert event is not None
        assert persisted["dispatch"][0]["dispatchId"] == notification["dispatchId"]
        assert persisted["dispatch"][0]["status"] == "published"

    asyncio.run(_run())


@pytest.mark.anyio
async def test_mixed_actions_do_not_publish_before_receipts_are_committed(tmp_path, monkeypatch):
    from app.alerts.outbox import AlertOutboxStore
    from app.alerts.webhook import WebhookSettings

    entered, resume = threading.Event(), threading.Event()
    settings = WebhookSettings(enabled=True, secret="test-signing-secret", allowed_hosts=("hooks.example.com",),
                               outbox_path=tmp_path / "outbox.sqlite3")
    outbox = AlertOutboxStore(settings.outbox_path)
    original = outbox.stage
    def stage(*args, **kwargs):
        entered.set()
        assert resume.wait(3)
        return original(*args, **kwargs)
    monkeypatch.setattr(outbox, "stage", stage)
    facade = AlertFacade(store_path=tmp_path / "alerts.json", webhook_settings=settings, outbox_store=outbox)
    subscription = facade.notification_broker.subscribe()
    emit = asyncio.create_task(facade.emit_triggered({
        "ruleId": "probe", "message": "hit", "actions": [
            {"type": "in_app"},
            {"type": "webhook", "config": {"url": "https://hooks.example.com/test"}},
        ],
    }, enforce_limits=False))
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        assert subscription.queue.empty()
    finally:
        resume.set()
    notification = await asyncio.wait_for(subscription.queue.get(), timeout=3)
    receipt = await run_storage(facade.record_dispatch_receipt, notification["eventId"],
                                notification["dispatchId"], status="delivered")
    await emit
    assert receipt is not None
    assert facade.list_history()[0]["dispatch"][0]["status"] == "delivered"


@pytest.mark.anyio
async def test_failed_dispatch_commit_never_publishes_browser_notification(tmp_path, monkeypatch):
    facade = AlertFacade(store_path=tmp_path / "alerts.json")
    subscription = facade.notification_broker.subscribe()
    def fail(*args):
        raise OSError("disk failure")
    monkeypatch.setattr(facade.store, "update_history_dispatch", fail)
    with pytest.raises(OSError, match="disk failure"):
        await facade.emit_triggered({"ruleId": "probe", "actions": [{"type": "in_app"}]}, enforce_limits=False)
    await asyncio.sleep(0)
    assert subscription.queue.empty()
    assert facade.notification_broker.snapshot()["published"] == 0
