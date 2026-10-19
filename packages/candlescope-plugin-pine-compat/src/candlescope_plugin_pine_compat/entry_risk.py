"""Capability handshake for Host-owned Pine entry risk enforcement."""
import pine_compat

CONTRACT = "candlescope.pine-entry-risk/1"
FUNCTIONS = {"strategy.risk.allow_entry_in", "strategy.risk.max_position_size"}


def available():
    return getattr(pine_compat, "STRATEGY_RISK_CONFIGURATION_SCHEMA_VERSION", 0) == 1


def options(request, analysis):
    features = {row.get("feature") for row in analysis.get("compatibility", {}).get("supported", [])}
    rules = {feature for feature in features if feature and feature.startswith("strategy.risk.")}
    if not rules:
        return {}
    if not available() or request.get("risk_contract") != CONTRACT or not rules <= FUNCTIONS:
        raise ValueError("EXTERNAL_UNSUPPORTED: Pine risk rules require a compatible Host enforcement contract")
    return {"risk_rules": True}
