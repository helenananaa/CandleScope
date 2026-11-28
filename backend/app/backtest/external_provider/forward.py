"""External models in forward runs (B-333c): live closed bars of one market, not a dataset.

A forward connection is scoped to its revision's manifest and one market series instead
of a frozen dataset snapshot, so neither kind of connection can serve the other kind of run.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import suppress
from typing import Any

from app.backtest.strategy.protocol import StrategyProviderError

from .provider import ExternalDecisionProvider

FORWARD_MARKET_FIELDS = ("exchange", "market_type", "symbol", "interval")


def forward_market(values: Mapping[str, Any]) -> dict[str, str]:
    """The market series a forward connection serves, from a run configuration or request."""
    market = {}
    for field in FORWARD_MARKET_FIELDS:
        value = values.get(field)
        if type(value) is not str or not 1 <= len(value) <= 128 or value != value.strip():
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "a forward connection names its exchange, market type, symbol and interval")
        market[field] = value
    return market


def forward_scope(revision_id: str, manifest_hash: str, market: Mapping[str, Any]) -> dict[str, Any]:
    return {"strategy_revision_id": revision_id, "manifest_hash": manifest_hash, "forward_market": forward_market(market)}


class ForwardExternalProvider(ExternalDecisionProvider):
    """An external model on a forward run: every Host start resumes the same session.

    A forward run has no end of history. Each Host that runs it takes the session over
    with the next generation (fencing every earlier owner), and closing a Host interrupts
    the session instead of sending the model its terminal ``close``. The next Host
    restores the checkpoint, replays committed decisions and continues.
    """

    def __init__(self, journal, *, connection_id: str, step_timeout_s: float) -> None:
        super().__init__(journal, connection_id=connection_id, host_generation=1, step_timeout_s=step_timeout_s)

    def bind_control(self, check_control) -> None:
        """Stop waiting for the model when the forward Host stops."""
        self.check_control = check_control

    def prepare(self, context: dict[str, Any]) -> None:
        if self.run_id is not None or self._closed:
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "external provider was already prepared")
        run_id = context.get("runId")
        if type(run_id) is not str:
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "external prepare requires a Host run identity")
        self.host_generation = self.journal.start_next(self.connection_id, run_id, context=context)
        self.run_id = run_id
        # Replays the recorded prepare reply after the first Host start.
        self._call("prepare", {"context": context})

    def snapshot(self) -> dict[str, Any]:
        self._ensure_prepared()
        return self.journal.snapshot(self.run_id, self.cursor, host_generation=self.host_generation, pin=False)

    def restore(self, payload: dict[str, Any]) -> None:
        self._ensure_prepared()
        cursor = payload.get("cursor")
        expected = self.journal.snapshot(self.run_id, cursor, host_generation=self.host_generation, pin=False)
        if payload != expected:
            raise StrategyProviderError("IDENTITY_MUTATION", "external checkpoint identity does not match the Host journal")
        self.cursor = cursor

    def close(self) -> str:
        if self.run_id is None or self._closed:
            self._closed = True
            return ""
        self._closed = True
        self._stopped.set()
        # A newer Host may already own the session; then there is nothing to interrupt.
        with suppress(StrategyProviderError):
            self.journal.interrupt(self.run_id, host_generation=self.host_generation)
        return ""
