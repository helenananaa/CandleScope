"""Frozen Pine entry constraints over the Host's live net position.

Session/equity stop rules require a separate event-driven execution contract.
They are deliberately rejected here, including rules in unreachable branches.
"""
from copy import deepcopy
from decimal import Decimal, InvalidOperation

from .errors import BacktestError

CONTRACT = "candlescope.pine-entry-risk/1"
FUNCTIONS = frozenset({"strategy.risk.allow_entry_in", "strategy.risk.max_position_size"})


class PineEntryRisk:
    def __init__(self):
        self.configuration = None
        self.directions = {Decimal(1), Decimal(-1)}
        self.maximum = None

    def configure(self, configuration):
        if (not isinstance(configuration, dict) or configuration.get("schemaVersion") != 1
                or configuration.get("unresolvedCallSiteIds") != []
                or not isinstance(configuration.get("rules"), list)):
            raise BacktestError("EXTERNAL_UNSUPPORTED", "resolved Pine risk configuration required")
        if self.configuration is not None:
            if configuration != self.configuration:
                raise BacktestError("EXTERNAL_NONCAUSAL_PREFIX", "Pine risk configuration changed")
            return
        directions, maximum, seen = {Decimal(1), Decimal(-1)}, None, set()
        for rule in configuration["rules"]:
            if (not isinstance(rule, dict) or rule.get("resolved") is not True
                    or rule.get("function") not in FUNCTIONS
                    or type(rule.get("callSiteId")) is not int or rule["callSiteId"] in seen):
                raise BacktestError("EXTERNAL_UNSUPPORTED", "unsupported Pine risk rule")
            seen.add(rule["callSiteId"])
            if rule["function"] == "strategy.risk.allow_entry_in":
                allowed = {"strategy.direction.all": {Decimal(1), Decimal(-1)},
                    "strategy.direction.long": {Decimal(1)}, "strategy.direction.short": {Decimal(-1)}}
                if rule.get("direction") not in allowed:
                    raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "invalid Pine entry direction")
                directions &= allowed[rule["direction"]]
            else:
                try:
                    value = Decimal(str(rule["value"]))
                except (KeyError, InvalidOperation, ValueError) as exc:
                    raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "invalid Pine position limit") from exc
                if not value.is_finite() or value <= 0:
                    raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "invalid Pine position limit")
                maximum = value if maximum is None else min(maximum, value)
        self.configuration = deepcopy(configuration)
        self.directions, self.maximum = directions, maximum

    def opening_quantity(self, requested, position, direction):
        if direction not in self.directions:
            return Decimal(0)
        if self.maximum is None:
            return requested
        available = max(Decimal(0), self.maximum - max(Decimal(0), position * direction))
        return min(requested, available)
