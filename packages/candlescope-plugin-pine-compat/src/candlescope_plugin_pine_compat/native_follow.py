"""Pine FOLLOW on one fixed history that grows as bars close (ADR-BACKTEST-015 O1, B-157a).

A chart's Pine strategy follows live bars by rebuilding a FIXED run over the latest
prefix after each bar close. This session keeps that history's engine state, so a
rebuild whose bars continue the previous one executes only the new bars. Each
result equals a FIXED run over the same bars (§3.4); a session opens only for
scripts where that holds and otherwise answers ``supported: false`` so the host
rebuilds in full.

Incremental and full execution differ when earlier bars see where the dataset
ends (``barstate.islast``, ``last_bar_index``, ``timenow`` ...), when the first
execution window depends on the dataset length (``calc_bars_count``), or when
other frozen inputs (contexts, magnifier, boundaries, session windows) would
have to grow with the bars. Those scripts keep full rebuilds.
"""
from __future__ import annotations

import re

import pine_compat

from .host_inputs import execution_times, native_inputs, normalize_native_request
from .native_strategy import pack, prepare, requested_bars
from .strategy_time import engine_bars

FOLLOW_CONTRACT = "candlescope.pine-follow/1"

# Builtins whose value on an earlier bar depends on the dataset's last bar, and
# requests, whose frozen data would have to grow with the chart's bars.
_HORIZON = re.compile(r"\b(?:barstate\s*\.\s*islast(?:confirmedhistory)?|session\s*\.\s*islastbar(?:_regular)?"
                      r"|last_bar_index|last_bar_time|timenow|chart\s*\.\s*right_visible_bar_time|request\s*\.)")
# Request fields that may grow between rebuilds; everything else must be identical.
_GROWING = frozenset({"bars", "execution_times", "operation", "identity", "identity_ref", "protocol"})


def available():
    return callable(getattr(getattr(pine_compat, "HistoricalSession", None), "extend", None))


def unsupported_reason(request, program):
    """Why incremental FOLLOW could differ from a full run of this request, or None."""
    if not available():
        return "engine cannot extend a fixed history"
    if request.get("operation") == "analyze" or not request.get("bars"):
        return "no bars"
    for field in ("contexts", "magnifier", "bar_boundaries", "signal_chart", "execution_events", "host_settings"):
        if request.get(field):
            return f"{field} are frozen with the bars"
    if (request.get("host_inputs") or {}).get("sessionWindows") or (request.get("host_inputs") or {}).get("barCalendars"):
        return "session windows are frozen with the bars"
    if getattr(program, "calculation_bars_count", None) is not None:
        return "calc_bars_count selects its window from the dataset length"
    sources = [request.get("source") or "", *(request.get("libraries") or {}).values()]
    for source in sources:
        if not isinstance(source, str) or _HORIZON.search(source):
            return "the script reads the dataset's last bar or requests other data"
    return None


def _static(request):
    return {key: value for key, value in request.items() if key not in _GROWING}


class FollowSession:
    def __init__(self, request, program, overrides, requirements, uses_magnifier):
        self.request = request
        self.requirements = requirements
        self.uses_magnifier = uses_magnifier
        _libraries, options = native_inputs(request)
        supplied = options.pop("request_bars") or {}
        supplied.update(requested_bars(request))
        if supplied:
            raise ValueError("NATIVE_FOLLOW_UNSUPPORTED: requested data is frozen with the bars")
        self.engine = program.historical_session(engine_bars(request["bars"]), input_overrides=overrides or None,
            chart_symbol=request["context"]["symbol"], chart_timeframe=request["context"]["timeframe"], **options)

    def advance(self, target):
        if target != len(self.request["bars"]) or self.engine.cursor != 0:
            raise ValueError("NATIVE_FOLLOW_MISMATCH: a follow session runs its history once, to its end")
        return pack(self.request, self.engine.advance(target), self.requirements, self.uses_magnifier)

    def extend(self, request):
        """The same input over bars that continue this session's: only the new bars execute."""
        request = normalize_native_request({key: value for key, value in request.items() if key != "operation"})
        old = self.request
        count = len(old["bars"])
        if self.engine.cursor != count:
            raise ValueError("NATIVE_FOLLOW_MISMATCH: the session has not reached its horizon")
        bars = request.get("bars") or []
        old_clocks = execution_times(old["bars"], old.get("execution_times"))
        clocks = execution_times(bars, request.get("execution_times"))
        if (_static(request) != _static(old) or len(bars) <= count or bars[:count] != old["bars"]
                or (old_clocks is None) != (clocks is None)
                or (clocks is not None and list(clocks[:count]) != list(old_clocks))):
            raise ValueError("NATIVE_FOLLOW_MISMATCH: the request does not continue this session's history")
        self.engine.extend(engine_bars(bars[count:]),
                           execution_times=None if clocks is None else list(clocks[count:]))
        self.request = request
        return pack(request, self.engine.advance(len(bars)), self.requirements, self.uses_magnifier)


def open_follow(request):
    """A FOLLOW session for ``request``, or None when only full rebuilds give FIXED's result."""
    request = normalize_native_request({key: value for key, value in request.items()
                                        if key not in {"operation", "follow_contract"}})
    program, overrides, requirements, uses_magnifier = prepare(request)
    if unsupported_reason(request, program) is not None:
        return None
    return FollowSession(request, program, overrides, requirements, uses_magnifier)
