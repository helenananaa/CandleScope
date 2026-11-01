"""Private account state snapshots; independent of public market subscriptions.

Wakeups coalesce commits. Each event replaces the complete overview; it is not
an event-by-event financial ledger or a resumable fill cursor.
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from app.readonly_accounts.normalization import AccountDataError

SCHEMA = "candlescope.readonly-account-state/1"


class AccountStateSubscription:
    def __init__(self, owner: ReadOnlyAccountDataManager) -> None:
        self.owner = owner
        self._updates = owner.service.repository.updates.subscribe("state")
        self._first = None
        self._iterating = False

    async def read(self) -> dict:
        self._updates.clear_before_read()
        value = await self.owner.service.state()
        if self._updates.closed:
            raise asyncio.CancelledError
        account = value["account"]
        return {"schema": SCHEMA, "type": "snapshot", "replacement": True,
                "identity": {"venue": value["venue"], "venueUid": account["venue_uid"] if account else None,
                             "epoch": value["cursor"]["epoch"]},
                "cursor": value["cursor"], "state": value}

    async def events(self) -> AsyncIterator[dict]:
        if self._iterating:
            raise RuntimeError("an account subscription has one consumer")
        self._iterating = True
        previous = None
        event, self._first = self._first, None
        try:
            while not self._updates.closed:
                if event is None:
                    event = await self.read()
                if event != previous:
                    yield event
                    previous = event
                event = None
                while not self._updates.closed:
                    try:
                        if not await asyncio.wait_for(self._updates.wait(), self.owner.heartbeat_seconds):
                            return
                        break
                    except TimeoutError:
                        yield {"schema": SCHEMA, "type": "heartbeat"}
        except Exception:
            yield {"schema": SCHEMA, "type": "error", "error": {"code": "ACCOUNT_STATE_STREAM_FAILED"}}
        finally:
            self.close()

    def close(self) -> None:
        self._first = None
        self._updates.close()
        self.owner._subscriptions.discard(self)


class ReadOnlyAccountDataManager:
    def __init__(self, service, *, max_subscriptions: int = 16, heartbeat_seconds: float = 15) -> None:
        if max_subscriptions < 1 or heartbeat_seconds <= 0:
            raise ValueError("account subscription limits must be positive")
        self.service = service
        self.max_subscriptions = max_subscriptions
        self.heartbeat_seconds = heartbeat_seconds
        self._closed = False
        self._control_requests = 0
        self._subscriptions: set[AccountStateSubscription] = set()

    def control_plane(self):
        self._check_open()
        self._control_requests += 1
        return self.service

    async def state(self) -> dict:
        self._check_open()
        return await self.service.state()

    def _check_open(self) -> None:
        if self._closed:
            raise AccountDataError("ACCOUNT_MANAGER_CLOSED")

    async def subscribe_state(self) -> AccountStateSubscription:
        self._check_open()
        if len(self._subscriptions) >= self.max_subscriptions:
            raise AccountDataError("ACCOUNT_SUBSCRIPTION_CAPACITY")
        subscription = AccountStateSubscription(self)
        self._subscriptions.add(subscription)
        try:
            subscription._first = await subscription.read()
            return subscription
        except BaseException:
            subscription.close()
            raise

    def diagnostics(self) -> dict:
        return {"closed": self._closed, "subscriptions": len(self._subscriptions), "control_requests": self._control_requests}

    def close(self) -> None:
        self._closed = True
        for subscription in tuple(self._subscriptions):
            subscription.close()
