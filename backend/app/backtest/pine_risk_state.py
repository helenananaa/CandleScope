"""Host risk-stop state over authoritative equity, realized PnL and windows.

This is the state machine, not an order matcher or a session-calendar provider.
The caller supplies causally ordered explicit window ordinals and actual fills,
then owns pending-order cancellation and market-close scheduling after a trip.
"""
from copy import deepcopy
from decimal import Decimal, InvalidOperation

from .errors import BacktestError

SCHEMA = "candlescope.pine-risk-state/1"
STOP_FUNCTIONS = frozenset("strategy.risk." + name for name in (
    "max_drawdown", "max_intraday_loss", "max_intraday_filled_orders", "max_cons_loss_days"))
ENTRY_FUNCTIONS = frozenset({"strategy.risk.allow_entry_in", "strategy.risk.max_position_size"})


def number(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "invalid Pine risk account value") from exc
    if not result.is_finite():
        raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "nonfinite Pine risk account value")
    return result


class PineRiskState:
    def __init__(self, configuration, *, initial_equity, initial_netprofit=0, window_policy):
        if (not isinstance(configuration, dict) or type(configuration.get("schemaVersion")) is not int
                or configuration["schemaVersion"] != 1 or configuration.get("unresolvedCallSiteIds") != []
                or not isinstance(configuration.get("rules"), list) or not isinstance(window_policy, str)
                or not window_policy):
            raise BacktestError("EXTERNAL_UNSUPPORTED", "resolved risk rules and an explicit window policy are required")
        self.configuration, self.window_policy = deepcopy(configuration), window_policy
        self.rules, seen = [], set()
        for rule in configuration["rules"]:
            if (not isinstance(rule, dict) or type(rule.get("callSiteId")) is not int
                    or rule["callSiteId"] < 0 or rule["callSiteId"] in seen
                    or rule.get("resolved") is not True or not isinstance(rule.get("function"), str)
                    or rule["function"] not in STOP_FUNCTIONS | ENTRY_FUNCTIONS):
                raise BacktestError("EXTERNAL_UNSUPPORTED", "unsupported Pine risk declaration")
            seen.add(rule["callSiteId"])
            if rule["function"] in ENTRY_FUNCTIONS:
                continue
            value = number(rule.get("value"))
            if value <= 0:
                raise BacktestError("EXTERNAL_UNSUPPORTED", "risk thresholds must be positive")
            if rule["function"].endswith(("max_cons_loss_days", "max_intraday_filled_orders")):
                if value != value.to_integral_value() or value > 4_294_967_295:
                    raise BacktestError("EXTERNAL_UNSUPPORTED", "risk counts must be positive u32 integers")
            elif (rule.get("valueType") not in {"strategy.cash", "strategy.percent_of_equity"}
                    or (rule["valueType"] == "strategy.percent_of_equity" and value > 100)):
                raise BacktestError("EXTERNAL_UNSUPPORTED", "invalid loss threshold type")
            self.rules.append((deepcopy(rule), value))
        self.initial_equity = number(initial_equity)
        if self.initial_equity <= 0:
            raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "positive initial equity required")
        self.peak = self.intraday_peak = self.initial_equity
        self.last_netprofit = self.session_netprofit = number(initial_netprofit)
        self.last_time = self.session = self.intraday = None
        self.loss_days = 0
        self.filled_orders = set()
        self.permanent, self.window_halts = set(), set()
        self.trips = []
        self.needs_session = any(rule["function"].endswith("max_cons_loss_days") for rule, _ in self.rules)
        self.needs_intraday = any("max_intraday_" in rule["function"] for rule, _ in self.rules)

    @property
    def blocked(self):
        return bool(self.permanent or self.window_halts)

    def observe(self, *, time_ms, equity, netprofit, session=None, intraday=None, filled_order_id=None):
        """Observe a market/account update or fill, including while halted.

        A filled order counts once per intraday window, including on its first
        partial fill. Subsequent partial fills still update equity/PnL. Forced
        risk closes should omit filled_order_id to avoid recursively counting
        the stop's own liquidation. This explicit partial-fill convention still
        requires official-output differential qualification.
        """
        equity, netprofit = number(equity), number(netprofit)
        if type(time_ms) is not int or time_ms < 0 or (self.last_time is not None and time_ms < self.last_time):
            raise BacktestError("EXTERNAL_NONCAUSAL_PREFIX", "risk observation clock moved backward")
        for needed, current, previous in ((self.needs_session, session, self.session),
                                         (self.needs_intraday, intraday, self.intraday)):
            if needed and (type(current) is not int or current < 0 or (previous is not None and current < previous)):
                raise BacktestError("EXTERNAL_NONCAUSAL_PREFIX", "explicit ordered risk windows required")
        if self.needs_session and self.session is not None and session > self.session + 1:
            raise BacktestError("EXTERNAL_RISK_WINDOW_GAP", "settle intervening trading sessions explicitly")
        if filled_order_id is not None and (not isinstance(filled_order_id, str) or not filled_order_id):
            raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "risk fill requires an actual order id")
        # Complete a session using its last observed realized profit, before
        # applying the first new session's funding, fees or market update.
        if self.needs_session and session != self.session:
            if self.session is not None:
                self.loss_days = self.loss_days + 1 if self.last_netprofit < self.session_netprofit else 0
                self.session_netprofit = self.last_netprofit
            self.session = session
        if self.needs_intraday and intraday != self.intraday:
            if self.intraday is not None:
                self.intraday_peak = equity
            self.intraday = intraday
            self.window_halts.clear()
            self.filled_orders.clear()
        if self.needs_intraday and filled_order_id is not None:
            self.filled_orders.add(filled_order_id)
        self.peak, self.intraday_peak = max(self.peak, equity), max(self.intraday_peak, equity)
        new = []
        for rule, threshold in self.rules:
            site, function = rule["callSiteId"], rule["function"]
            if site in self.permanent or site in self.window_halts:
                continue
            permanent, triggered = True, False
            if function.endswith("max_cons_loss_days"):
                triggered = self.loss_days >= threshold
            elif function.endswith("max_intraday_filled_orders"):
                permanent, triggered = False, len(self.filled_orders) >= threshold
            else:
                intraday_loss = function.endswith("max_intraday_loss")
                permanent = not intraday_loss
                peak = self.intraday_peak if intraday_loss else self.peak
                if rule["valueType"] == "strategy.cash":
                    triggered = peak - equity >= threshold
                elif equity <= 0:
                    permanent, triggered = True, True
                else:
                    triggered = (peak - equity) * 100 >= peak * threshold
            if triggered:
                (self.permanent if permanent else self.window_halts).add(site)
                trip = {"callSiteId": site, "function": function, "time_ms": time_ms,
                    "session": self.session, "intraday": self.intraday, "permanent": permanent,
                    "equity": str(equity), "peak": str(self.peak), "intraday_peak": str(self.intraday_peak),
                    "netprofit": str(netprofit), "filled_order_count": len(self.filled_orders),
                    "consecutive_loss_days": self.loss_days,
                    **({"alert_message": rule["alertMessage"]} if "alertMessage" in rule else {})}
                self.trips.append(trip)
                new.append(deepcopy(trip))
        self.last_time, self.last_netprofit = time_ms, netprofit
        return new

    def snapshot(self):
        return {"schema": SCHEMA, "configuration": deepcopy(self.configuration), "window_policy": self.window_policy,
            "initial_equity": str(self.initial_equity), "peak": str(self.peak), "intraday_peak": str(self.intraday_peak),
            "last_netprofit": str(self.last_netprofit), "session_netprofit": str(self.session_netprofit),
            "last_time": self.last_time, "session": self.session, "intraday": self.intraday, "loss_days": self.loss_days,
            "filled_orders": sorted(self.filled_orders), "permanent": sorted(self.permanent),
            "window_halts": sorted(self.window_halts), "trips": deepcopy(self.trips)}

    def restore(self, state):
        if (state.get("schema") != SCHEMA or state.get("configuration") != self.configuration
                or state.get("window_policy") != self.window_policy
                or number(state.get("initial_equity")) != self.initial_equity):
            raise BacktestError("CHECKPOINT_CORRUPT", "Pine risk checkpoint identity differs")
        values = {name: number(state[name]) for name in ("peak", "intraday_peak", "last_netprofit", "session_netprofit")}
        sites = {rule["callSiteId"] for rule, _ in self.rules}
        for key in ("permanent", "window_halts"):
            if not isinstance(state.get(key), list) or not set(state[key]) <= sites:
                raise BacktestError("CHECKPOINT_CORRUPT", "Pine risk halt identities differ")
        if (type(state.get("loss_days")) is not int or state["loss_days"] < 0
                or not isinstance(state.get("filled_orders"), list)
                or any(not isinstance(value, str) or not value for value in state["filled_orders"])
                or not isinstance(state.get("trips"), list)):
            raise BacktestError("CHECKPOINT_CORRUPT", "invalid Pine risk checkpoint state")
        for key in ("session", "intraday", "last_time"):
            if state.get(key) is not None and (type(state[key]) is not int or state[key] < 0):
                raise BacktestError("CHECKPOINT_CORRUPT", "invalid Pine risk checkpoint cursor")
        for key, value in values.items():
            setattr(self, key, value)
        for key in ("last_time", "session", "intraday", "loss_days"):
            setattr(self, key, state[key])
        self.filled_orders = set(state["filled_orders"])
        self.permanent, self.window_halts = set(state["permanent"]), set(state["window_halts"])
        self.trips = deepcopy(state["trips"])
