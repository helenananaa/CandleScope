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
from .pine_contract_metadata import bind_account_metadata


def _settings(payload):
    names = WorkbenchBarSettings.model_fields
    try:
        return WorkbenchBarSettings.model_validate({k: payload[k] for k in names if k in payload})
    except ValidationError as exc:
        raise BacktestError("SCHEMA_UNKNOWN_FIELD", "invalid Workbench account settings") from exc


def freeze_grid(wire, payload):
    settings = _settings(payload)
    if settings.account_model != "LINEAR_PERP_ONE_WAY_V2":
        if wire.get("account_model") == "SPOT_CASH_V1" and (wire["context"].get("metadata") or {}).get("pointValue", 1) != 1:
            raise BacktestError("FIDELITY_UNSUPPORTED", "spot cash accounting requires unit pointValue")
        return settings
    account = LinearPerpetualAccountV2(funding_mode=settings.funding_mode)
    opening = wire["bars"][0]["time"] * 1000
    try:
        for index, row in enumerate(settings.account_data.events):
            if row.time_ms > opening:
                break
            account.apply(MarketEvent(index + 1, row.time_ms, row.role, row.payload))
        account.validate_ready()
    except MarketDatasetError as exc:
        raise BacktestError(exc.code, str(exc)) from exc
    supplied = payload.get("context", {}).get("metadata") or {}
    metadata = bind_account_metadata(account, supplied)
    cached = wire["context"].get("metadata") or {}
    if "currency" not in metadata and cached.get("currency"):
        metadata["currency"] = cached["currency"]
    wire["context"] = {**wire["context"], "metadata": metadata}
    wire["host_settings"] = {**wire["host_settings"], "price_tick": str(account.tick)}
    return settings


def freeze_account(wire, payload, *, settings=None):
    settings = settings or _settings(payload)
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
    from .pine_print_account import FIDELITIES, CONTRACT as PRINT_CONTRACT
    physical = wire["execution_fidelity"] in FIDELITIES
    if payload.get("language") != "pine" or (not physical and (
            not wire.get("pine_bar_path_contract") or wire["execution_fidelity"] != "BAR_APPROX")):
        raise BacktestError("FIDELITY_UNSUPPORTED", "Workbench V2 requires Pine BAR callbacks or a frozen physical clock")
    if physical:
        if model != "LINEAR_PERP_ONE_WAY_V2":
            raise BacktestError("FIDELITY_UNSUPPORTED", "extended physical account settings require V2")
        if settings.bar_path_scenario is not None:
            raise BacktestError("FIDELITY_MISLABEL", "physical clocks cannot use a synthetic BAR path")
        if settings.execution_model_revision is not None and wire["execution_fidelity"] != "TRADE_TAPE":
            raise BacktestError("FIDELITY_UNSUPPORTED", "book capacity retains its declared physical policy")
    if settings.execution_model_revision is not None and settings.participation_rate is None:
        raise BacktestError("FIDELITY_UNSUPPORTED", "V2 participation_rate is required")
    if settings.execution_model_revision is None and (settings.participation_rate is not None or settings.bar_path_scenario is not None):
        raise BacktestError("FIDELITY_UNSUPPORTED", "participation settings require EXECUTION_REALISM_V2")
    if model != "LINEAR_PERP_ONE_WAY_V2" and (settings.account_data is not None or settings.funding_mode != "OFF" or settings.leverage != 1):
        raise BacktestError("FIDELITY_UNSUPPORTED", "historical account data requires the V2 perpetual account")
    wire.update(account_model=model, **({"pine_v2_print_contract": PRINT_CONTRACT} if physical else {"pine_v2_bar_contract": CONTRACT}),
        pine_v2_settings={"leverage": str(settings.leverage), "funding_mode": settings.funding_mode,
            "execution_model_revision": settings.execution_model_revision,
            "participation_rate": None if settings.participation_rate is None else str(settings.participation_rate),
            "bar_path_scenario": PINE_BAR_PATH_SCENARIO if settings.execution_model_revision and not physical else None})
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
                metadata = wire["context"].get("metadata") or {}
                if Fraction(str(metadata.get("pointValue", 1))) != Fraction(account.multiplier):
                    raise BacktestError("FIDELITY_UNSUPPORTED", "Pine pointValue must remain constant within one frozen run")
                metadata_tick = metadata.get("priceTickSize")
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
