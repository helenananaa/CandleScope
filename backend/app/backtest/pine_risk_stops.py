"""Pine stop rules enforced through the actual Host order matcher."""
from copy import deepcopy

from app.data_engine.interval_policy import parse_interval_spec
from .errors import BacktestError
from .pine_risk_state import PineRiskState, STOP_FUNCTIONS, ENTRY_FUNCTIONS

CONTRACT = "candlescope.pine-risk-stops/1"
DAY_MS = 86_400_000
LIVE = {"OPEN", "PARTIAL"}


def window_contract(config, functions):
    windowed = any(name.endswith(("max_cons_loss_days", "max_intraday_loss", "max_intraday_filled_orders")) for name in functions)
    if not windowed:
        return {"policy": "NON_WINDOWED_V1"}
    if (str(config.get("exchange") or "").lower() != "binance"
            or str(config.get("market_type") or "").lower() not in {"spot", "usdm", "futures", "swap"}):
        raise BacktestError("FIDELITY_UNSUPPORTED", "Pine daily risk requires explicit Binance continuous-market metadata")
    interval = config.get("signal_interval") or config.get("interval")
    if not isinstance(interval, str):
        raise BacktestError("FIDELITY_UNSUPPORTED", "Pine daily risk requires an explicit chart interval")
    spec = parse_interval_spec(interval)
    above_day = spec.next_ms(0) - spec.floor_ms(0) > DAY_MS
    if (above_day and config.get("fidelity_mode") == "BAR_APPROX"
            and "strategy.risk.max_cons_loss_days" in functions):
        raise BacktestError("FIDELITY_UNSUPPORTED", "consecutive loss days require daily account observations, not multi-day OHLC bars")
    return {"policy": "BINANCE_UTC_24_7_V1", "interval": interval, "intraday_per_bar": above_day}


class PineRiskStops:
    def __init__(self, orders, config):
        self.orders, self.kernel, self.config = orders, orders.kernel, dict(config or {})
        self.configuration = self.state = self.windows = None
        self.execution_cursor = 0
        self.flatten_requested = False
        self.close_serial = 0
        self.actions = []
        orders.risk_stops = self

    def configure(self, configuration, *, observe=True):
        if (not isinstance(configuration, dict) or configuration.get("schemaVersion") != 1
                or configuration.get("unresolvedCallSiteIds") != []
                or not isinstance(configuration.get("rules"), list)):
            raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "resolved Pine risk configuration required")
        if self.configuration is not None:
            if configuration != self.configuration:
                raise BacktestError("EXTERNAL_NONCAUSAL_PREFIX", "Pine risk configuration changed")
            return
        functions = {rule.get("function") for rule in configuration.get("rules", [])}
        if not functions <= STOP_FUNCTIONS | ENTRY_FUNCTIONS:
            raise BacktestError("EXTERNAL_UNSUPPORTED", "unknown Pine risk rule")
        windows = window_contract(self.config, functions)
        if self.config.get("pine_risk_windows") is not None and self.config["pine_risk_windows"] != windows:
            raise BacktestError("IDENTITY_MUTATION", "Pine risk window contract changed")
        import json
        state = PineRiskState(configuration, initial_equity=self.kernel.initial_balance,
            window_policy=json.dumps(windows, sort_keys=True)) if functions & STOP_FUNCTIONS else None
        entry = {**configuration, "rules": [rule for rule in configuration["rules"] if rule["function"] in ENTRY_FUNCTIONS]}
        if entry["rules"]:
            self.orders.entry_risk.configure(entry)
        self.configuration, self.windows, self.state = deepcopy(configuration), windows, state
        if state is not None:
            self.kernel.market_observer = self.observe_market
        if observe and state is not None and self.kernel._last_event is not None:
            cursor = getattr(self.kernel, "_market_event_count", 0)
            self.execution_cursor = cursor or self.kernel._last_event.sequence
            self.observe_market(self.kernel._last_event, update_cursor=False)

    @property
    def blocked(self):
        return (getattr(self.kernel.account, "liquidation_event", None) is not None
            or self.state is not None and (self.state.blocked or self.flatten_requested))

    def observe_market(self, event, *, update_cursor=True):
        if self.state is None:
            return
        if update_cursor and event.role in {"BARS", "TRADES"}:
            self.execution_cursor = event.sequence
        self._observe(event.event_time_ms)
        self._enforce(event)

    def after_fill(self, execution):
        if self.state is None or not execution.get("fill"):
            return
        fill, order_id = execution["fill"], execution["order_id"]
        self.execution_cursor = fill["sequence"]
        kind = self.orders.details[order_id]["kind"]
        observation_time = max(fill["event_time_ms"], self.kernel._last_event.event_time_ms)
        self._observe(observation_time, None if kind in {"risk_close", "liquidation"} else order_id)
        if not self.kernel.account.position_qty:
            self.flatten_requested = False
        self._enforce(self.kernel._last_event)

    def _observe(self, time_ms, order_id=None):
        from .external import account_feedback_profit
        session = intraday = None
        if self.windows["policy"] == "BINANCE_UTC_24_7_V1":
            session = time_ms // DAY_MS
            spec = parse_interval_spec(self.windows["interval"])
            intraday = (spec.floor_ms(time_ms) - spec.floor_ms(0) if self.windows["intraday_per_bar"] else session)
        account = self.kernel.account
        self.state.observe(time_ms=time_ms, equity=account.equity(),
            netprofit=account_feedback_profit(account, self.kernel.initial_balance),
            session=session, intraday=intraday, filled_order_id=order_id)

    def _enforce(self, event):
        if not self.blocked:
            return
        working = self.kernel._live_orders() if hasattr(self.kernel, "_live_orders") else self.kernel._working_orders()
        pending_close = False
        for order in tuple(working):
            if order.status in LIVE:
                if self.orders.details[order.order_id]["kind"] == "risk_close":
                    pending_close = True
                else:
                    self.orders.cancel_order(order, "PINE_RISK_STOP")
        position = self.kernel.account.position_qty
        if not position:
            self.flatten_requested = False
            return
        self.flatten_requested = True
        if pending_close:
            return
        self.close_serial += 1
        token = f"pine-risk-close-{self.close_serial}"
        self.orders.staged_bindings[token] = ("$host:pine-risk-close", {
            "kind": "risk_close", "owner": None, "remaining": abs(position),
            "submitted_sequence": event.sequence, "submitted_time": event.event_time_ms})
        self.actions.append({"action": "MARKET_CLOSE_SUBMITTED", "time_ms": event.event_time_ms,
            "execution_sequence": self.execution_cursor, "client_tag": token, "qty": str(abs(position))})
        self.kernel._enqueue_many([{"side": "SELL" if position > 0 else "BUY", "type": "MARKET",
            "qty": str(abs(position)), "reduce_only": True, "client_tag": token}], current_sequence=self.execution_cursor)
        # Rejected closes remain visible and are retried on the next observed
        # market/account event. They never fabricate a fill or debit the account.
        self.orders.staged_bindings.pop(token, None)

    def snapshot(self):
        return {"contract": CONTRACT, "windows": deepcopy(self.windows), "state": self.state.snapshot(),
            "execution_cursor": self.execution_cursor, "flatten_requested": self.flatten_requested,
            "close_serial": self.close_serial, "actions": deepcopy(self.actions)}

    def restore(self, payload):
        if payload.get("contract") != CONTRACT:
            raise BacktestError("CHECKPOINT_CORRUPT", "Pine stop contract differs")
        self.configure(payload["state"]["configuration"], observe=False)
        if self.state is None or payload.get("windows") != self.windows:
            raise BacktestError("CHECKPOINT_CORRUPT", "Pine stop window policy differs")
        for name in ("execution_cursor", "close_serial"):
            if type(payload.get(name)) is not int or payload[name] < 0:
                raise BacktestError("CHECKPOINT_CORRUPT", "invalid Pine stop cursor")
        if type(payload.get("flatten_requested")) is not bool:
            raise BacktestError("CHECKPOINT_CORRUPT", "invalid Pine flatten state")
        self.state.restore(payload["state"])
        self.execution_cursor, self.close_serial = payload["execution_cursor"], payload["close_serial"]
        self.flatten_requested, self.actions = payload["flatten_requested"], deepcopy(payload["actions"])

    def report(self):
        return {"contract": CONTRACT, "windows": deepcopy(self.windows), "blocked": self.blocked,
            "flatten_requested": self.flatten_requested, "residual_position": str(self.kernel.account.position_qty),
            "trips": deepcopy(self.state.trips), "actions": deepcopy(self.actions),
            "fill_count_convention": "FIRST_POSITIVE_FILL_PER_ORDER_PER_WINDOW",
            "close_timing": "NEXT_MATCHING_TICK_WITH_HOST_CAPACITY_AND_LATENCY"}
