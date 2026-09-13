"""Versioned, certified market-only Python execution in a supervised worker."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from decimal import Decimal

from .protocol import ProviderCapabilities, StrategyProviderError, canonical_hash

EXECUTION_PROTOCOL = "MARKET_BATCH_V1"
BATCH_PROTOCOL = "candlescope.python-market-batch/1"
RECEIPT_SCHEMA = "candlescope.python-market-batch-receipt/1"
CERTIFIED_SMA_SOURCE = "0b79c9f406ef27aa6ae21badd415ae0127756bbbd2d6b6624c70840275983a8c"
BATCH_ROWS = 256
MAX_PACKET_BYTES = 256 * 1024


def certified_source(bundle, entrypoint="strategy:Strategy"):
    source = (Path(bundle) / "strategy.py").read_bytes().replace(b"\r\n", b"\n")
    if entrypoint != "strategy:Strategy" or hashlib.sha256(source).hexdigest() != CERTIFIED_SMA_SOURCE:
        raise StrategyProviderError("FIDELITY_UNSUPPORTED", "market batch requires a certified causal implementation")
    return source


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


class PythonMarketBatchProvider:
    def __init__(self, bundle, events, *, entrypoint="strategy:Strategy", warmup_events=0, full_outputs=True):
        self.bundle = Path(bundle)
        self.source = certified_source(bundle, entrypoint)
        if type(events) is not tuple or any(event.role != "BARS" for event in events):
            raise StrategyProviderError("FIDELITY_UNSUPPORTED", "market batch requires a materialized BAR-only snapshot")
        self.events = events
        self.warmup_events = warmup_events
        self.full_outputs = full_outputs

    def describe(self):
        return ProviderCapabilities(input_modes=("BAR_CLOSE",), output_modes=("TARGET_POSITION",), signal_clock="BAR_CLOSE")

    def prepare(self, context):
        self.parameters = dict(context.get("parameters") or {})
        if set(self.parameters) != {"fast", "slow"} or any(
            type(v) is not int or not 2 <= v <= 512 for v in self.parameters.values()
        ):
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "certified SMA periods must be integers in 2..512")
        self.lookback = max(self.parameters.values()) - 1
        namespace = {"__name__": "_certified_market_batch"}
        # Compile the verified source directly; do not trust a bundle pyc cache.
        exec(compile(self.source, str(self.bundle / "strategy.py"), "exec"), namespace)
        self.calculate = namespace["Strategy"].calculate_batch
        self.offset = 0
        self.pending = None
        self.receipts = []
        self.chain = canonical_hash({"protocol": BATCH_PROTOCOL, "sourceHash": CERTIFIED_SMA_SOURCE,
                                     "runId": context.get("runId"), "parameters": self.parameters,
                                     "warmupRows": self.warmup_events, "batchRows": BATCH_ROWS})

    def _batch(self, start):
        from candlescope_backtest_sdk.batch import MarketBatch, BAR_COLUMNS
        context_start = max(0, start - self.lookback)
        end = min(start + BATCH_ROWS, len(self.events))
        selected = self.events[context_start:end]
        columns = {"sequence": [e.sequence for e in selected],
                   "event_time_ms": [e.event_time_ms for e in selected]}
        for name in BAR_COLUMNS:
            # Same missing/falsey-field conversion as the scalar host adapter.
            columns[name] = [str(e.payload.get(name) or "0") for e in selected]
        raw = {"columns": columns, "contextRows": start-context_start,
               "warmupRows": min(end-start, max(0, self.warmup_events-start))}
        estimated = len(_encoded(raw))
        for name in BAR_COLUMNS:
            for value in columns[name]:
                if len(value.encode("utf-8")) > 65536:
                    raise StrategyProviderError("MESSAGE_TOO_LARGE", "market batch decimal string exceeds budget")
                if "e" in value.lower():
                    number = Decimal(value)
                    if number.is_finite():
                        sign, digits, exponent = number.as_tuple()
                        expanded = max(len(digits) + max(exponent, 0),
                                       max(len(digits) + exponent, 1) + max(-exponent, 0) + 1) + sign
                        if expanded > 65536:
                            raise StrategyProviderError("MESSAGE_TOO_LARGE", "market batch decimal expansion exceeds budget")
                        estimated += max(0, expanded - len(value))
        if estimated > MAX_PACKET_BYTES:
            raise StrategyProviderError("MESSAGE_TOO_LARGE", "market batch input exceeds its frozen byte budget")
        batch = MarketBatch.from_columns(columns, context_rows=raw["contextRows"], warmup_rows=raw["warmupRows"])
        packet = batch.to_wire()
        packet["parameters"] = self.parameters
        encoded = _encoded(packet)
        if len(encoded) > MAX_PACKET_BYTES:
            raise StrategyProviderError("MESSAGE_TOO_LARGE", "normalized market batch exceeds its frozen byte budget")
        return batch, "sha256:" + hashlib.sha256(encoded).hexdigest()

    def _fill(self):
        batch, input_hash = self._batch(self.offset)
        targets = self.calculate(batch, dict(self.parameters))
        expected = len(batch.sequence) - batch.context_rows
        if type(targets) is not tuple or len(targets) != expected:
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "market batch output length mismatch")
        if any(value not in (None, "1", "-1") for value in targets):
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "invalid certified SMA target")
        if any(value is not None for value in targets[:batch.warmup_rows]):
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "market batch warmup emitted targets")
        if any(value not in ("1", "-1") for value in targets[batch.warmup_rows:]):
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "market batch evaluation omitted targets")
        self.pending = {"start": self.offset, "targets": list(targets), "inputHash": input_hash,
                        "outputHash": canonical_hash({"protocol": BATCH_PROTOCOL, "targets": targets})}

    def warmup(self, frame):
        return self.step(frame)

    def step(self, frame):
        if self.offset >= len(self.events):
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "market batch exhausted")
        event = self.events[self.offset]
        if event.sequence != frame.sequence or event.event_time_ms != frame.event_time_ms:
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "market batch source clock changed")
        if (frame.phase == "WARMUP") != (self.offset < self.warmup_events):
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "market batch warmup boundary changed")
        if self.pending is None:
            self._fill()
        pending = self.pending
        target = pending["targets"][self.offset - pending["start"]]
        self.offset += 1
        if self.offset == pending["start"] + len(pending["targets"]):
            receipt = {"ordinal": len(self.receipts)+1, "sourceOffset": pending["start"],
                       "rowCount": len(pending["targets"]),
                       "firstSequence": self.events[pending["start"]].sequence,
                       "lastSequence": event.sequence, "inputHash": pending["inputHash"],
                       "outputHash": pending["outputHash"]}
            self.chain = canonical_hash({"previous": self.chain, "batch": receipt})
            self.receipts.append(receipt)
            self.pending = None
        if target is None:
            return None
        if not self.full_outputs:
            # Private legacy planner value, never represented as a V1 receipt.
            return {"kind": "TARGET_POSITION", "payload": {"quantity": target, "targetExposure": target}}
        from .python_provider import _to_host_output
        wire = {"schemaVersion": "candlescope.python-strategy-output/1", "sequence": event.sequence,
                "kind": "TARGET_POSITION", "payload": {"quantity": target}}
        wire["outputHash"] = canonical_hash(wire)
        return _to_host_output(event.sequence, wire)

    def on_execution_report(self, report):
        # The session verifies generation before this boundary. Exclude the
        # operational generation so recovery preserves the semantic receipt.
        value = {k: v for k, v in report.items() if k != "generation"}
        value = json.loads(json.dumps(value, default=str, allow_nan=False))
        self.chain = canonical_hash({"previous": self.chain, "execution": value})

    def snapshot(self):
        return {"protocol": BATCH_PROTOCOL, "offset": self.offset, "chain": self.chain,
                "parameters": dict(self.parameters), "warmupRows": self.warmup_events,
                "pending": deepcopy(self.pending), "receipts": deepcopy(self.receipts)}

    def restore(self, payload):
        if (payload.get("protocol") != BATCH_PROTOCOL or payload.get("parameters") != self.parameters
                or payload.get("warmupRows") != self.warmup_events):
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "market batch checkpoint identity mismatch")
        offset = payload["offset"]
        if type(offset) is not int or not 0 <= offset <= len(self.events):
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "invalid market batch cursor")
        pending = deepcopy(payload.get("pending"))
        if pending is not None:
            start = pending["start"]
            if type(start) is not int or start < 0 or start % BATCH_ROWS or not start <= offset < start + len(pending["targets"]):
                raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "invalid pending market batch")
            batch, input_hash = self._batch(start)
            if (pending["inputHash"] != input_hash
                    or len(pending["targets"]) != len(batch.sequence) - batch.context_rows
                    or pending["outputHash"] != canonical_hash({"protocol": BATCH_PROTOCOL, "targets": pending["targets"]})
                    or tuple(pending["targets"]) != self.calculate(batch, dict(self.parameters))):
                raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "pending market batch receipt mismatch")
        elif offset % BATCH_ROWS and offset != len(self.events):
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "missing pending market batch")
        receipt_count = offset // BATCH_ROWS if pending is not None else (offset+BATCH_ROWS-1) // BATCH_ROWS
        if not isinstance(payload.get("receipts"), list) or len(payload["receipts"]) != receipt_count:
            raise StrategyProviderError("PROVIDER_PROTOCOL_VIOLATION", "market batch receipt count mismatch")
        self.offset, self.pending = offset, pending
        self.chain = str(payload["chain"])
        self.receipts = deepcopy(payload["receipts"])

    def close(self):
        return canonical_hash({"protocol": RECEIPT_SCHEMA, "chain": self.chain, "consumedRows": self.offset,
                               "pending": self.pending})

    def report_metadata(self):
        partial = {}
        if self.pending is not None:
            partial = {"partialBatch": {"sourceOffset": self.pending["start"],
                "plannedRows": len(self.pending["targets"]), "consumedRows": self.offset-self.pending["start"],
                "inputHash": self.pending["inputHash"], "outputHash": self.pending["outputHash"]}}
        return {"pythonBatchReceipt": {"schemaVersion": RECEIPT_SCHEMA, "receiptHash": self.close(),
                "consumedRows": self.offset, "batchRows": BATCH_ROWS, "sourceHash": CERTIFIED_SMA_SOURCE,
                "batches": deepcopy(self.receipts), **partial}}
