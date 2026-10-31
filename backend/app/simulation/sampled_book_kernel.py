"""Bounded sampled L2; no inferred passive queue fills or exchange continuity."""
from dataclasses import dataclass
from .depth_kernel import DepthQueueKernel, depth_error
from .trade_kernel import _print_triggers_stop
from decimal import Decimal


@dataclass(slots=True)
class SampledBookKernel(DepthQueueKernel):
    fill_policy: str = "SAMPLED_L2_VISIBLE_TAKER_ONLY_V1"
    sample_time_ms: int | None = None
    max_age_ms: int = 2000
    stale_trade_events: int = 0

    def snapshot(self, *, history_encoder=None):
        return {**DepthQueueKernel.snapshot(self,history_encoder=history_encoder),
            "sampled_state":{"schema":"sampled-book/1","sample_time_ms":self.sample_time_ms,
                "max_age_ms":self.max_age_ms,"stale_trade_events":self.stale_trade_events}}

    def restore(self,payload):
        from .book_checkpoint import corrupt
        state=payload.get("sampled_state") or {}
        stamp,count=state.get("sample_time_ms"),state.get("stale_trade_events")
        if (state.get("schema")!="sampled-book/1" or state.get("max_age_ms")!=self.max_age_ms
                or (stamp is not None and type(stamp) is not int) or type(count) is not int or count<0
                or (stamp is None)!=(payload.get("book_state",{}).get("sequence") is None)):
            corrupt("sampled-book checkpoint identity differs")
        DepthQueueKernel.restore(self,payload)
        self.sample_time_ms,self.stale_trade_events=stamp,count

    def _validate_book(self, event):
        data = event.payload
        seq, observed = data.get("sample_index"), data.get("sample_time_ms")
        if data.get("depth_scope") != "BOUNDED_SAMPLED" or data.get("depth_complete") is not False:
            depth_error("sampled book must declare bounded, incomplete depth")
        if "book_sequence" in data or data.get("reset"):
            depth_error("sample indices must not masquerade as exchange book sequences")
        if type(seq) is not int or seq < 1 or (self.book_sequence is not None and seq != self.book_sequence + 1):
            depth_error("sample index gap or reset")
        if type(observed) is not int or observed > event.event_time_ms:
            depth_error("sample time must not be in the future")
        if self.book_sequence is None:
            if data.get("snapshot") is not True or event.event_time_ms - observed > self.max_age_ms:
                depth_error("sampled book requires a recent initial snapshot")
        elif observed != event.event_time_ms or observed <= self.sample_time_ms:
            depth_error("later book samples must retain strictly increasing source times")
        return seq

    def _apply_book(self, event):
        DepthQueueKernel._apply_book(self, event)
        self.sample_time_ms = event.payload["sample_time_ms"]

    def _passive_allowed(self):
        return False

    def _match(self, event):
        from .v2_margin import reprice
        if event.role == "ORDER_BOOK":
            self._apply_book(event)
            reprice(self, event)
            return
        reprice(self, event)
        if self.sample_time_ms is None:
            depth_error("trade precedes sampled book")
        if event.event_time_ms < self.sample_time_ms:
            depth_error("trade precedes visible sample time")
        # The archive has no cross-stream ordering. New same-ms book information
        # cannot be used for matching that millisecond's prints.
        if event.event_time_ms == self.sample_time_ms:
            self._observe_unmatched_print(event)
            return
        if event.event_time_ms - self.sample_time_ms > self.max_age_ms:
            self.stale_trade_events += 1
            self._observe_unmatched_print(event)
            return
        DepthQueueKernel._match(self, event)

    def _observe_unmatched_print(self, event):
        # Stop and trailing state still sees prices while stale liquidity cannot fill.
        for order in self.orders:
            if order.status not in {"OPEN", "PARTIAL"} or order.eligible_after_sequence > event.sequence:
                continue
            if self.order_policy and not self.order_policy(order, event):
                continue
            if order.type in {"STOP", "STOP_LIMIT"} and _print_triggers_stop(order, Decimal(str(event.payload['price']))):
                order.activated = True

    def disclosure(self):
        return {"queue_exact": False, "depth_scope": "BOUNDED_SAMPLED",
                "passive_policy": "NO_INFERRED_PASSIVE_FILLS", "taker_clock": "next_trade_print",
                "taker_capacity": "remaining_visible_depth", "depth_exhaustion": "leave_unfilled",
                "same_timestamp_policy": "trades_before_new_book_sample",
                "max_book_age_ms": self.max_age_ms, "stale_trade_events": self.stale_trade_events,
                "exchange_sequence_verified": False}
