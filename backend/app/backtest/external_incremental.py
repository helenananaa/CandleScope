"""Negotiate Pyne's versioned callbacks without transmitting old prefixes."""
from .errors import BacktestError

CONTRACT = "pyne.host-fixed-history/1"


class IncrementalEvaluator:
    def __init__(self, worker, horizon):
        self.worker, self.horizon = worker, horizon
        self.mode = None
        self.cursor = 0
        self.context_counts = {}
        self.intents = []

    def __call__(self, _plugin, payload, **kwargs):
        request = payload
        if self.mode is None:
            request = {**payload, "evaluation": {"contract": CONTRACT, "horizon": self.horizon, "cursor": 0}}
        elif self.mode == CONTRACT:
            if len(payload["bars"]) != self.cursor + 1:
                raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "incremental host cursor changed")
            request = {"protocol": payload["protocol"], "identity": payload["identity"],
                       "evaluation": {"contract": CONTRACT, "horizon": self.horizon, "cursor": self.cursor},
                       "bars": payload["bars"][-1:], "accounts": payload["accounts"][-1:], "contexts": []}
            for item in payload.get("contexts", []):
                offset = self.context_counts[(item["symbol"], item["timeframe"])]
                request["contexts"].append({**item, "offset": offset, "bars": item["bars"][offset:]})
        result = self.worker.request(request, **kwargs)
        mode = result.get("evaluation_contract")
        if mode not in {CONTRACT, "historical-prefix/1"}:
            raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "unknown evaluator contract")
        if self.mode is not None and mode != self.mode:
            raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "incremental evaluator contract changed")
        self.mode = mode
        if mode == CONTRACT:
            current = result["intents"]
            if len(current) > 64 or any(item["bar_index"] != self.cursor for item in current):
                raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "invalid incremental intent cursor")
            self.intents.extend(current)
            result = {**result, "intents": list(self.intents)}
            self.cursor += 1
            self.context_counts = {(item["symbol"], item["timeframe"]): len(item["bars"])
                                   for item in payload.get("contexts", [])}
        return result
