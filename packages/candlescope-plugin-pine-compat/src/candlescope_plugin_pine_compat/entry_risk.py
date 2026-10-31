"""Capability handshake for Host-owned Pine entry risk enforcement."""
import pine_compat

CONTRACT = "candlescope.pine-entry-risk/1"
FUNCTIONS = {"strategy.risk.allow_entry_in", "strategy.risk.max_position_size"}
STOP_CONTRACT = "candlescope.pine-risk-stops/1"
STOP_FUNCTIONS = {"strategy.risk." + name for name in (
    "max_drawdown", "max_intraday_loss", "max_intraday_filled_orders", "max_cons_loss_days")}


def available():
    return getattr(pine_compat, "STRATEGY_RISK_CONFIGURATION_SCHEMA_VERSION", 0) == 1


def options(request, analysis):
    features = {row.get("feature") for row in analysis.get("compatibility", {}).get("supported", [])}
    rules = {feature for feature in features if feature and feature.startswith("strategy.risk.")}
    if not rules:
        return {}
    allowed = FUNCTIONS | STOP_FUNCTIONS if request.get("risk_contract") == STOP_CONTRACT else FUNCTIONS
    if not available() or request.get("risk_contract") not in {CONTRACT, STOP_CONTRACT} or not rules <= allowed:
        raise ValueError("EXTERNAL_UNSUPPORTED: Pine risk rules require a compatible Host enforcement contract")
    return {"risk_rules": True}
