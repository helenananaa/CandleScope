"""Finite, private creation preflight for the first continuing BAR contract.

The controller supplies a Manager-owned semantic series. This creates no run,
version, snapshot, demand or provider process, and cannot reset an existing run.
"""
from __future__ import annotations

from collections.abc import Mapping

from app.data_engine.data_manager.models import SeriesKey
from app.market_dataset.snapshot import MarketDatasetError
from app.simulation.execution_realism import parse_execution_realism
from .continuous_provider import prepare_provider, _json
from .errors import BacktestError
from .models import ENGINE_VERSION
from .service import _base_execution_contract, _config_decimal, _config_optional_decimal

BASE_FIELDS = {"account_model","gap_policy","contract_data_mode","funding_mode","leverage",
    "initial_balance","slippage_bps","taker_fee_bps","maker_fee_bps","funding_rate","funding_interval_hours",
    "price_tick","qty_step","min_notional","quick_preset_id","quick_preset_revision","fee_source"}
POLICY_FIELDS = {"sizing_policy","fixed_qty","fixed_notional","equity_percent","risk_per_stop_percent",
    "stop_distance","max_abs_position_qty","max_notional","max_leverage","max_order_risk","max_active_orders",
    "max_cumulative_fees","max_drawdown_percent","daily_loss_limit","cooldown_events"}
REALISM_FIELDS = {"execution_model_revision","participation_rate","order_end_policy","bar_path_scenario"}


def prepare_definition(provider, execution, key: SeriesKey, *, warmup_bars=0):
    """Own current code and normalized fees/account before acquiring any data."""
    if not isinstance(execution, Mapping) or set(execution)-(BASE_FIELDS|POLICY_FIELDS|REALISM_FIELDS):
        raise BacktestError("CONTINUOUS_INPUT_INVALID","Unknown continuing execution fields")
    if len(_json(dict(execution)).encode("utf-8")) > 65_536:
        raise BacktestError("BUDGET_EXCEEDED","Execution configuration exceeds its budget")
    if type(warmup_bars) is not int or not 0 <= warmup_bars <= 200_000:
        raise BacktestError("CONTINUOUS_INPUT_INVALID","Warmup must be a bounded closed BAR count")
    for name in ("funding_interval_hours","max_active_orders","cooldown_events"):
        if name in execution and type(execution[name]) is not int:
            raise BacktestError("CONTINUOUS_INPUT_INVALID",f"{name} must be an integer")
    if (not isinstance(key,SeriesKey) or key.interval!="1m" or key.market_type not in {"spot","futures"}
            or (key.market_type=="futures" and key.exchange!="binance")
            or key.identity.asset_class!="crypto" or key.identity.series_variant!="native"
            or key.identity.price_adjustment!="raw" or key.identity.session_variant!="continuous"
            or key.identity.volume_semantics!="base_asset"):
        raise BacktestError("FIDELITY_UNSUPPORTED","This continuous source requires qualified native crypto UTC 1m OHLCV")
    provider = prepare_provider(provider)
    payload = {**execution,"output_mode":provider["output_mode"],"market_type":key.market_type}
    try:
        (account_model, contract_mode, funding_mode, leverage, funding_rate, funding_hours,
            _output_mode, policy, preset, preset_revision, fee_source) = _base_execution_contract(payload)
        realism = parse_execution_realism(payload,fidelity_mode="BAR_APPROX")
    except MarketDatasetError as failure:
        raise BacktestError(failure.code,str(failure)) from failure
    except (TypeError,ValueError,OverflowError) as failure:
        raise BacktestError("CONTINUOUS_INPUT_INVALID","Invalid continuing execution value") from failure
    if (account_model not in {"LINEAR_PERP_ONE_WAY_V1","SPOT_CASH_V1"}
            or contract_mode!="LEGACY_FIXED_V1" or funding_mode!="OFF" or funding_rate!=0 or leverage!=1):
        raise BacktestError("FIDELITY_UNSUPPORTED","This continuation requires its qualified V1 account, leverage 1 and funding OFF")
    if (key.market_type=="spot") != (account_model=="SPOT_CASH_V1"):
        raise BacktestError("CONTINUOUS_INPUT_INVALID","Account model must match the owned market product")
    # Gap SKIP/PAUSE and end-of-history liquidation are not live-tail recovery.
    if str(payload.get("gap_policy") or "REJECT")!="REJECT":
        raise BacktestError("FIDELITY_UNSUPPORTED","Continuous inputs require complete coverage, with no silent skips")
    if not realism.enabled and any(name in execution for name in REALISM_FIELDS-{"execution_model_revision"}):
        raise BacktestError("CONTINUOUS_INPUT_INVALID","Execution realism fields require its explicit model revision")
    if not policy and any(name in execution for name in POLICY_FIELDS-{"sizing_policy"}):
        raise BacktestError("CONTINUOUS_INPUT_INVALID","Sizing and risk fields require an explicit Host policy")
    config = {"account_model":account_model,"warmup_bars":warmup_bars,
        "initial_balance":str(_config_decimal(payload,"initial_balance","10000")),
        "slippage_bps":str(_config_decimal(payload,"slippage_bps","1")),
        "taker_fee_bps":str(_config_decimal(payload,"taker_fee_bps","0")),
        "maker_fee_bps":str(_config_decimal(payload,"maker_fee_bps","0")),
        "funding_rate":"0","funding_mode":"OFF","funding_interval_hours":funding_hours,
        "gap_policy":"REJECT","exchange":key.exchange,"market_type":key.market_type,
        "symbol":key.symbol,"interval":key.interval}
    for name in ("price_tick","qty_step","min_notional"):
        value = _config_optional_decimal(payload,name)
        if value is not None:config[name] = str(value)
    if policy:config.update(policy.identity())
    if preset:config.update(quick_preset_id=preset,quick_preset_revision=preset_revision,fee_source=fee_source)
    config.update(realism.identity(fidelity_mode="BAR_APPROX"))
    series = [key.exchange,key.market_type,key.symbol,key.interval,*key.identity.storage_values]
    return {"engine_version":ENGINE_VERSION,"language":provider["language"],"provider":provider,
        "configuration":config,"input_plan":{"roles":["BARS"]},
        "source_kind":"MARKET_BAR","source_series":series,
        "market":{"venue":key.exchange,"symbol":key.symbol}}
