"""Host strategy-provider/1 bridge; the model executes outside the Host."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from contextlib import suppress
from typing import Any

from app.backtest.strategy.protocol import (
    ObservationFrame,
    ProviderCapabilities,
    StrategyOutput,
    StrategyProviderError,
)

from .journal import ExternalCallJournal
from .messages import decision_output, observation_payload


class ExternalHostInterrupted(BaseException):
    """Graceful Host shutdown requeues work instead of recording model failure."""


class ExternalDecisionProvider:
    def __init__(self, journal: ExternalCallJournal, *, connection_id: str, host_generation: int,
                 step_timeout_s: float, check_control: Callable[[], None] | None = None) -> None:
        if step_timeout_s <= 0:
            raise ValueError("external provider timeout must be positive")
        self.journal = journal
        self.connection_id = connection_id
        self.host_generation = host_generation
        self.step_timeout_s = step_timeout_s
        self.check_control = check_control
        self.run_id: str | None = None
        self.cursor = 0
        self._stopped = threading.Event()
        self._closed = False

    def describe(self) -> ProviderCapabilities:
        return self.journal.manifest.capabilities()

    def identity(self) -> dict[str, Any]:
        return self.journal.manifest.identity()

    def prepare(self, context: dict[str, Any]) -> None:
        if self.run_id is not None or self._closed:
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "external provider was already prepared")
        run_id = context.get("runId")
        if type(run_id) is not str:
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "external prepare requires a Host run identity")
        self.journal.start(self.connection_id, run_id, host_generation=self.host_generation, context=context)
        self.run_id = run_id
        self._call("prepare", {"context": context})

    def warmup(self, frame: ObservationFrame) -> None:
        if frame.phase != "WARMUP":
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "external warmup requires a warmup observation")
        self._observe("warmup", frame)

    def step(self, frame: ObservationFrame) -> StrategyOutput | None:
        return self._observe("step", frame)

    def _observe(self, operation: str, frame: ObservationFrame) -> StrategyOutput | None:
        if frame.run_id != self.run_id:
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "external observation belongs to another run")
        payload = observation_payload(frame, self.journal.manifest)
        if operation == "step" and frame.phase != "EVALUATION":
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "external step requires an evaluation observation")
        reply = self._call(operation, {"observation": payload})
        return decision_output(self.journal.manifest, reply["decision"], sequence=frame.sequence,
                               state_hash=reply["model_state_hash"])

    def on_execution_report(self, report: dict[str, Any]) -> None:
        # Host generation fences the envelope; it is not a model input. Keeping
        # it out of semantic report bytes permits exact replay after recovery.
        self._call("onExecutionReport", {"report": {key: value for key, value in report.items() if key != "generation"}})

    def snapshot(self) -> dict[str, Any]:
        self._ensure_prepared()
        return self.journal.snapshot(self.run_id, self.cursor, host_generation=self.host_generation)

    def restore(self, payload: dict[str, Any]) -> None:
        self._ensure_prepared()
        cursor = payload.get("cursor")
        expected = self.journal.snapshot(self.run_id, cursor, host_generation=self.host_generation)
        if payload != expected:
            raise StrategyProviderError("IDENTITY_MUTATION", "external checkpoint identity does not match the Host journal")
        self.cursor = cursor

    def report_metadata(self) -> dict[str, Any]:
        self._ensure_prepared()
        return {"external_provider": self.journal.audit(self.run_id, self.cursor, host_generation=self.host_generation)}

    def close(self) -> str:
        if self.run_id is None or self._closed or self._stopped.is_set():
            self._closed = True
            return ""
        try:
            self._call("close", {})
            return self.journal.audit(self.run_id, self.cursor, host_generation=self.host_generation)["trace_hash"]
        finally:
            self._closed = True

    def abort(self) -> None:
        self._stopped.set()
        if self.run_id is not None:
            self.journal.interrupt(self.run_id, host_generation=self.host_generation)

    def _ensure_prepared(self) -> None:
        if self.run_id is None:
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "prepare external provider first")

    def _call(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._ensure_prepared()
        if self._closed or self._stopped.is_set():
            raise StrategyProviderError("PROVIDER_CRASH_UNRECOVERABLE", "external provider is closed")
        deadline = time.monotonic() + self.step_timeout_s
        next_cursor = self.cursor + 1
        try:
            if self.check_control is not None:
                self.check_control()
            record = self.journal.enqueue(self.run_id, host_generation=self.host_generation, cursor=next_cursor,
                                          operation=operation, payload=payload, now_ms=int(time.time() * 1000))
            while record["reply"] is None:
                if self.check_control is not None:
                    self.check_control()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise StrategyProviderError("PROVIDER_TIMEOUT", "external model call exceeded the Host step budget")
                if self._stopped.wait(min(0.01, remaining)):
                    raise StrategyProviderError("PROVIDER_CRASH_UNRECOVERABLE", "external provider was interrupted")
                record = self.journal.recorded(self.run_id, next_cursor, host_generation=self.host_generation)
            self.cursor = next_cursor
            reply = record["reply"]
            if "error" in reply:
                # External error text is recorded privately, but cannot inject
                # arbitrary content into Host logs or public failure messages.
                raise StrategyProviderError(reply["error"]["code"], "external model reported a bounded execution failure")
            return reply
        except BaseException:
            # Cleanup cannot replace the primary Host/model failure, and must
            # not log an external exception's potentially private message.
            with suppress(Exception):
                self.abort()
            raise
