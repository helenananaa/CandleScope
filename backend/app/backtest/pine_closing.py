"""Chart orchestration for explicit simulated closing-tick execution."""
from app.market_dataset.snapshot import sha256_hex
from app.simulation.closing_tick import CONTRACT, match_closing_tick
from app.simulation.kernel import _decision_record


class ChartClosingTicks:
    def __init__(self, kernel, callbacks=None):
        self.kernel, self.callbacks = kernel, callbacks

    def process(self, bar, sequence):
        execution = getattr(self.kernel, "execution", self.kernel)
        match_closing_tick(execution, bar, sequence, on_fill=self.on_fill if self.callbacks else None)

    def on_fill(self, bar, tick):
        intents = (self.callbacks.observe_closing_fill(bar) if hasattr(self.callbacks,"observe_closing_fill")
                   else self.callbacks.observe(bar, confirmed=True))
        wire = getattr(intents, "decision", None) or {}
        decision = _decision_record(intents, sequence=wire.get("sequence", bar.sequence), watermark_ms=bar.event_time_ms)
        decision.update(trigger="CLOSE_FILL", signal_sequence=bar.sequence, source_sequence=tick.sequence,
            closing_tick_contract=CONTRACT)
        if self.kernel.scale_stream_decisions:
            self.kernel._decision_chain_hash = "sha256:" + sha256_hex({"previous":self.kernel._decision_chain_hash,"decision":decision})
            self.kernel._decision_count += 1
        else:
            self.kernel.decisions.append(decision)
        self.kernel.execution._enqueue_many(intents, current_sequence=tick.sequence - 1)
