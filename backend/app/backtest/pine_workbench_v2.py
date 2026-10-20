"""Frozen Workbench V2 BAR inputs; the shared Host kernel owns all money."""
from fractions import Fraction

from pydantic import ValidationError

from app.market_dataset.snapshot import MarketEvent, MarketDatasetError
from app.simulation.linear_perp_account_v2 import LinearPerpetualAccountV2
from app.simulation.pine_v2_bar_kernel import CONTRACT
from app.simulation.execution_realism import PINE_BAR_PATH_SCENARIO
from .errors import BacktestError
from .native_contracts import WorkbenchBarSettings
from .pine_workbench import bar_event


def freeze_account(wire, payload):
    names = WorkbenchBarSettings.model_fields
    try:
        settings = WorkbenchBarSettings.model_validate({k: payload[k] for k in names if k in payload})
    except ValidationError as exc:
        raise BacktestError("SCHEMA_UNKNOWN_FIELD", "invalid Workbench account settings") from exc
    default_model = "SPOT_CASH_V1" if payload.get("market_type", "usdm") == "spot" else "LINEAR_PERP_ONE_WAY_V1"
    model = settings.account_model or default_model
    extended = (model == "LINEAR_PERP_ONE_WAY_V2" or settings.execution_model_revision is not None)
    if model != default_model and not (model == "LINEAR_PERP_ONE_WAY_V2" and default_model != "SPOT_CASH_V1"):
        raise BacktestError("FIDELITY_UNSUPPORTED", "Workbench account model differs from the market")
    if (not extended and (settings.account_data is not None or settings.funding_mode != "OFF" or settings.leverage != 1
                         or settings.participation_rate is not None or settings.bar_path_scenario is not None)):
        raise BacktestError("FIDELITY_UNSUPPORTED", "V2 account/capacity settings require their explicit model")
    if not extended:
        return
    if payload.get("language") != "pine" or not wire.get("pine_bar_path_contract") or wire["execution_fidelity"] != "BAR_APPROX":
        raise BacktestError("FIDELITY_UNSUPPORTED", "Workbench V2 BAR requires Pine historical fill callbacks")
    if settings.execution_model_revision is not None and settings.participation_rate is None:
        raise BacktestError("FIDELITY_UNSUPPORTED", "V2 participation_rate is required")
    if settings.execution_model_revision is None and (settings.participation_rate is not None or settings.bar_path_scenario is not None):
        raise BacktestError("FIDELITY_UNSUPPORTED", "participation settings require EXECUTION_REALISM_V2")
    if model != "LINEAR_PERP_ONE_WAY_V2" and (settings.account_data is not None or settings.funding_mode != "OFF" or settings.leverage != 1):
        raise BacktestError("FIDELITY_UNSUPPORTED", "historical account data requires the V2 perpetual account")
    wire.update(account_model=model, pine_v2_bar_contract=CONTRACT,
        pine_v2_settings={"leverage": str(settings.leverage), "funding_mode": settings.funding_mode,
            "execution_model_revision": settings.execution_model_revision,
            "participation_rate": None if settings.participation_rate is None else str(settings.participation_rate),
            "bar_path_scenario": PINE_BAR_PATH_SCENARIO if settings.execution_model_revision else None})
    data = settings.account_data
    if model == "LINEAR_PERP_ONE_WAY_V2" and data is None:
        raise BacktestError("DATA_ROLE_MISSING", "V2 Workbench requires frozen historical account_data")
    if data is None:
        wire["account_events"] = []
        return
    if data.symbol != wire["context"]["symbol"].split(":")[-1]:
        raise BacktestError("DATA_SNAPSHOT_MISMATCH", "account-data symbol differs from chart")
    first_open = wire["bars"][0]["time"] * 1000
    last_close = bar_event(wire, len(wire["bars"]) - 1, 0).event_time_ms
    account = LinearPerpetualAccountV2(funding_mode=settings.funding_mode)
    previous = None
    roles = set()
    ready = False
    try:
        for index, row in enumerate(data.events):
            if previous is not None and row.time_ms < previous or row.time_ms > last_close:
                raise BacktestError("DATA_QUALITY_FAILED", "account events must be ordered within the frozen horizon")
            if row.time_ms > first_open and not ready:
                account.validate_ready()
                ready = True
            previous = row.time_ms
            account.apply(MarketEvent(index + 1, row.time_ms, row.role, row.payload))
            roles.add(row.role)
            if row.role == "INSTRUMENT_RULES":
                if account.multiplier != 1:
                    raise BacktestError("FIDELITY_UNSUPPORTED", "nonunit Pine contract metadata remains unsupported")
                metadata_tick = (wire["context"].get("metadata") or {}).get("priceTickSize")
                if metadata_tick is not None and Fraction(str(metadata_tick)) != Fraction(account.tick):
                    raise BacktestError("DATA_SNAPSHOT_MISMATCH", "historical tick differs from Pine chart metadata")
        account.validate_ready()
    except MarketDatasetError as exc:
        raise BacktestError(exc.code, str(exc)) from exc
    required = {"INSTRUMENT_RULES", "MARK_INDEX"} | ({"FUNDING"} if settings.funding_mode == "HISTORICAL_REQUIRED" else set())
    if not required <= roles or not any(row.role == "MARK_INDEX" and row.time_ms <= first_open for row in data.events):
        raise BacktestError("DATA_ROLE_COVERAGE_MISSING", "historical account roles must cover the opening observation")
    wire["account_events"] = [row.model_dump() for row in data.events]
    wire["account_provenance"] = data.provenance


def events(wire):
    """Auxiliary events precede the canonical BAR close on timestamp ties."""
    rows = [bar_event(wire, index, 0) for index in range(len(wire["bars"]))]
    rows.extend(MarketEvent(0, row["time_ms"], row["role"], row["payload"]) for row in wire["account_events"])
    rows.sort(key=lambda row: (row.event_time_ms, row.role == "BARS"))
    return [MarketEvent(index + 1, row.event_time_ms, row.role, row.payload) for index, row in enumerate(rows)]
