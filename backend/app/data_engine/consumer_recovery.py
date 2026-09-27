"""Terminal delivery gaps. A new subscription requires a fresh source snapshot."""
from __future__ import annotations

from typing import Awaitable, Callable


class ConsumerRecoveryRequired(RuntimeError):
    code = "CONSUMER_RESYNC_REQUIRED"

    def __init__(
        self, reason: str, *, subscription_id: str = "", epoch: str = "",
        confirmed_sequence: int = 0, first_missing_sequence: int | None = None,
    ) -> None:
        super().__init__(f"{self.code}: {reason}")
        self.reason = reason
        self.subscription_id = subscription_id
        self.epoch = epoch
        self.confirmed_sequence = confirmed_sequence
        self.first_missing_sequence = first_missing_sequence

    def to_dict(self) -> dict:
        return {
            "code": self.code, "reason": self.reason,
            "subscription_id": self.subscription_id, "epoch": self.epoch,
            "confirmed_sequence": self.confirmed_sequence,
            "first_missing_sequence": self.first_missing_sequence,
            "recovery": "snapshot_then_resubscribe",
        }


RecoveryCallback = Callable[[ConsumerRecoveryRequired], Awaitable[None]]


def terminate_queue(queue, terminal) -> None:
    """Wake a bounded iterator even when its backlog fills every slot."""
    while not queue.empty():
        queue.get_nowait()
    queue.put_nowait(terminal)
