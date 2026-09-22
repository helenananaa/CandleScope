"""Select immutable auxiliary inputs without changing replay account fidelity."""
from app.replay.training.models import TrainingRunSetupRequest, TrainingRunMarketSelectionRequest

from .models import PreparationError


async def prepare_replay_dependencies(training, request):
    setup = request.intent.get("replay_setup", {})
    if setup.get("account_data_mode") != "HISTORICAL_EXACT":
        return {}
    if training is None or getattr(training, "account_history", None) is None:
        raise PreparationError("AUXILIARY_HISTORY_UNAVAILABLE", "Historical account archive service is unavailable")
    if setup.get("start_mode") != "MANUAL":
        raise PreparationError("AUXILIARY_RANGE_REQUIRED", "Exact account history requires a fixed historical start")
    market = request.requirements[0]
    selection = TrainingRunMarketSelectionRequest.from_dict({
        "catalog_epoch": "sha256:" + "0" * 64,
        "exchange": market.exchange, "market_type": market.market_type, "symbol": market.symbol,
        "base_interval": "1m", "display_interval": request.intent.get("display_interval", "1m"),
        "account_history_ref": None, "hedge_public_history_ref": None, "simulation_manifest_ref": None,
    })
    model = TrainingRunSetupRequest.from_dict(setup).for_market(selection)
    plan = await training.account_history.plan_for_request(model)
    reference = plan.get("account_history_ref")
    if plan.get("capability_state") != "AVAILABLE_EXACT" or not reference:
        raise PreparationError("AUXILIARY_HISTORY_UNAVAILABLE",
            "Historical mark prices, versioned contract rules and required funding history are unavailable "
            f"for the selected range ({plan.get('reason', 'UNKNOWN')}); the requested account model was retained")
    # The engine validates the selected reference again when binding the run.
    # These engine-owned objects never become acquisition-cache GC candidates.
    return {"account_history_ref": reference, "hedge_public_history_ref": None, "simulation_manifest_ref": None}
