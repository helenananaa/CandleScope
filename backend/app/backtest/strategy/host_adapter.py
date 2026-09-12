from __future__ import annotations

from typing import Any

from .serial_worker import SerialWorker

from .protocol import (
    ObservationFrame,
    StrategyProviderError,
    StrategyProviderSession,
    canonical_hash,
)


class StrategyHostAdapter:
    """Maps a backtest run to a strategy-provider session. No kernel fills."""

    def __init__(
        self,
        session: StrategyProviderSession,
        *,
        step_timeout_s: float = 2.0,
        inline: bool = False,
    ) -> None:
        self.session = session
        self.step_timeout_s = step_timeout_s
        self._worker: SerialWorker | None = None
        self._closed = False
        self._inline = inline

    def close(self) -> None:
        self._closed = True
        if self._worker is not None:
            self._worker.close()

    def __del__(self) -> None:
        worker = getattr(self, "_worker", None)
        if worker is not None:
            worker.close(wait=False)

    def start(self, input_plan: dict[str, Any]) -> dict[str, Any]:
        described = self.session.describe()
        self.session.prepare(
            {"runId": self.session.run_id, "inputPlan": input_plan, **input_plan}
        )
        return described

    def observe(
        self,
        *,
        sequence: int,
        event_time_ms: int,
        watermark_ms: int,
        phase: str,
        market: dict[str, str],
        bar: dict[str, Any] | None,
        features: dict[str, Any] | None = None,
        trade: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if event_time_ms > watermark_ms:
            raise StrategyProviderError("LOOKAHEAD_VIOLATION", "host refused future bar")
        frame = ObservationFrame(
            run_id=self.session.run_id,
            sequence=sequence,
            event_time_ms=event_time_ms,
            watermark_ms=watermark_ms,
            phase=phase,
            market=market,
            input_hash=canonical_hash(
                {
                    "sequence": sequence,
                    "watermark": watermark_ms,
                    "bar": bar,
                    "trade": trade,
                    "features": features,
                }
            ),
            bar=bar,
            trade=trade,
            features=features or {},
        )
        if self._closed:
            raise StrategyProviderError("PROVIDER_TIMEOUT", "adapter is closed")
        if self._worker is None and not self._inline:
            self._worker = SerialWorker(f"strategy-step-{self.session.run_id}")

        def invoke() -> Any:
            if phase == "WARMUP":
                self.session.warmup(frame)
                return None
            return self.session.step(frame)

        try:
            if self._inline:
                # Only used inside a supervised whole-run worker. The parent
                # enforces provider deadlines by terminating that process.
                output = invoke()
            else:
                assert self._worker is not None
                output = self._worker.call(invoke, self.step_timeout_s)
        except TimeoutError:
            self._closed = True
            abort = getattr(self.session.provider, "abort", None)
            if callable(abort):
                abort()
            raise StrategyProviderError("PROVIDER_TIMEOUT", "provider step exceeded budget")
        return None if output is None else output.to_wire()

    def reject_host_write(self, attempt: str) -> None:
        raise StrategyProviderError(
            "PROVIDER_UNAUTHORIZED_WRITE",
            f"provider cannot write {attempt}",
        )
