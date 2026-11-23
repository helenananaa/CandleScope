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
    "signal_chart","price_tick","qty_step","min_notional","quick_preset_id","quick_preset_revision","fee_source",
    "account_rules"}
POLICY_FIELDS = {"sizing_policy","fixed_qty","fixed_notional","equity_percent","risk_per_stop_percent",
    "stop_distance","max_abs_position_qty","max_notional","max_leverage","max_order_risk","max_active_orders",
    "max_cumulative_fees","max_drawdown_percent","daily_loss_limit","cooldown_events"}
REALISM_FIELDS = {"execution_model_revision","participation_rate","order_end_policy","bar_path_scenario"}


def _fixed_interval(interval):
    from app.data_engine.interval_policy import IntervalAlignment, parse_interval_spec
    spec = parse_interval_spec(interval)
    return spec is not None and not spec.timezone and spec.alignment is not IntervalAlignment.CALENDAR_MONTH


def prepare_definition(provider, execution, key: SeriesKey, *, warmup_bars=0, follow=False):
    """Own current code and normalized fees/account before acquiring any data.

    ``follow`` (ADR-BACKTEST-015 P4b): a FOLLOW run consumes the chart's own closed
    bars, so any fixed-length chart interval qualifies; forward runs keep 1m.
    """
    if not isinstance(execution, Mapping) or set(execution)-(BASE_FIELDS|POLICY_FIELDS|REALISM_FIELDS):
        raise BacktestError("CONTINUOUS_INPUT_INVALID","Unknown continuing execution fields")
    if len(_json(dict(execution)).encode("utf-8")) > 65_536:
        raise BacktestError("BUDGET_EXCEEDED","Execution configuration exceeds its budget")
    if type(warmup_bars) is not int or not 0 <= warmup_bars <= 200_000:
        raise BacktestError("CONTINUOUS_INPUT_INVALID","Warmup must be a bounded closed BAR count")
    for name in ("funding_interval_hours","max_active_orders","cooldown_events"):
        if name in execution and type(execution[name]) is not int:
            raise BacktestError("CONTINUOUS_INPUT_INVALID",f"{name} must be an integer")
    if (not isinstance(key,SeriesKey) or (key.interval!="1m" and not (follow and _fixed_interval(key.interval)))
            or key.market_type not in {"spot","futures"}
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
    from app.simulation.practice_clock import PRACTICE_ACCOUNT_RULES
    practice = "account_rules" in execution
    if practice and (execution["account_rules"]!=PRACTICE_ACCOUNT_RULES or realism.enabled):
        raise BacktestError("FIDELITY_UNSUPPORTED","Practice account rules run without execution realism")
    # The practice account model (ADR-BACKTEST-015 P6e3) holds margin at the account's leverage;
    # the qualified V1 contract account keeps leverage 1.
    if (account_model not in {"LINEAR_PERP_ONE_WAY_V1","SPOT_CASH_V1"}
            or contract_mode!="LEGACY_FIXED_V1" or funding_mode!="OFF" or funding_rate!=0 or (leverage!=1 and not practice)):
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
    if payload.get("signal_chart") is not None:
        from app.data_engine.synthetic_series.signals import normalize_signal_chart
        try:config["signal_chart"] = normalize_signal_chart(payload["signal_chart"])
        except ValueError as exc:raise BacktestError("CONTINUOUS_INPUT_INVALID",str(exc)) from exc
    if practice:config.update(account_rules=PRACTICE_ACCOUNT_RULES,leverage=str(leverage))
    if policy:config.update(policy.identity())
    if preset:config.update(quick_preset_id=preset,quick_preset_revision=preset_revision,fee_source=fee_source)
    config.update(realism.identity(fidelity_mode="BAR_APPROX"))
    series = [key.exchange,key.market_type,key.symbol,key.interval,*key.identity.storage_values]
    return {"engine_version":ENGINE_VERSION,"language":provider["language"],"provider":provider,
        "configuration":config,"input_plan":{"roles":["BARS"]},
        "source_kind":"MARKET_BAR","source_series":series,
        "market":{"venue":key.exchange,"symbol":key.symbol}}
