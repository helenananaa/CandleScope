"""Opt-in, closed-bar Pine notifications through the existing alert facade."""
import hashlib
import json
from app.core.executors import run_storage


class PineAlerts:
    def __init__(self, facade):
        self.facade = facade

    async def observe(self, request, result):
        if (request.language != "pine" or not result.ok or not request.options.get("pineAlerts")
                or not request.transport.startswith("websocket.")):
            return
        facade = self.facade()
        if facade is None:
            result.meta["pineAlertStatus"] = "unavailable"
            return
        target = {"exchange": request.exchange, "marketType": request.market_type,
                  "symbol": request.symbol, "interval": request.interval}
        identity = json.dumps([request.source, request.params, request.options.get("pineAlertInputs"), target],
                              sort_keys=True, separators=(",", ":"))
        rule_id = "pine-" + hashlib.sha256(identity.encode()).hexdigest()[:32]
        rule = await run_storage(facade.get_rule, rule_id)
        if rule is None:
            rule = await run_storage(facade.save_rule, {
                "id": rule_id, "name": f"Pine · {request.symbol} {request.interval}",
                "description": "Pine closed-bar alerts; requires this indicator to remain subscribed. Configure delivery here; enable from the indicator editor.",
                "enabled": True, "target": target, "triggerOn": "bar_close",
                "expression": {"left": "pineAlert", "comparator": "==", "right": {"type": "number", "value": 1}},
                "actions": [{"type": "in_app", "enabled": True, "config": {}}],
                "cooldownMs": 0, "maxTriggers": None, "afterTrigger": "keep", "tags": ["pine"]})
        result.meta["pineAlertRuleId"] = rule_id
        result.meta["pineAlertStatus"] = "armed" if rule["enabled"] else "paused"
        expected_expression = {"left": "pineAlert", "comparator": "==", "right": {"type": "number", "value": 1}}
        if rule["target"] != target or rule["expression"] != expected_expression or rule["triggerOn"] != "bar_close":
            result.meta["pineAlertStatus"] = "modified"
            return
        if not request.options.get("pineLiveUpdate") or result.meta.get("sessionReset"):
            return
        closed = {bar.time * 1000 if bar.time < 100_000_000_000 else bar.time
                  for bar in request.to_sdk_request().bars if bar.is_closed}
        if not closed:
            return
        live_time = int(request.options.get("pineLiveBarTime") or 0)
        last = live_time * 1000 if live_time < 100_000_000_000 else live_time
        if last not in closed:
            return
        counts = {}
        for event in result.meta.get("pineAlerts", []):
            if event.get("time") != last:
                continue
            callsite = str(event.get("id"))
            ordinal = counts.get(callsite, 0)
            counts[callsite] = ordinal + 1
            key = f"{rule_id}:{last}:{callsite}:{ordinal}"
            await facade.emit_triggered({"id": "pine-" + hashlib.sha256(key.encode()).hexdigest(),
                "ruleId": rule_id, "target": target, "message": str(event.get("message") or "Pine alert"),
                "values": {"pineAlert": 1, "barTime": last, "callSite": callsite, "occurrence": ordinal}})
