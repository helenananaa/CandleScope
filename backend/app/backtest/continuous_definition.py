"""Finite, private creation preflight for the first continuing BAR contract.

The controller supplies a Manager-owned semantic series. This creates no run,
version, snapshot, demand or provider process, and cannot reset an existing run.
"""
from __future__ import annotations

from collections.abc import Mapping

from app.data_engine.data_manager.models import SeriesKey
from app.data_engine.history.expected_bars import session_calendar
from app.exchanges.roles import BINANCE_USDM_LINEAR_BASE_QUANTITY, CONTRACT_RULES, venue_role_contract
from app.market_dataset.snapshot import MarketDatasetError
from app.simulation.execution_realism import parse_execution_realism
from .continuous_grid import supports as grid_interval
from .continuous_provider import prepare_provider, _json
from .errors import BacktestError
from .models import ENGINE_VERSION
from .execution_contract import _base_execution_contract, _config_decimal, _config_optional_decimal

BASE_FIELDS = {"account_model","gap_policy","contract_data_mode","funding_mode","leverage",
    "initial_balance","slippage_bps","taker_fee_bps","maker_fee_bps","funding_rate","funding_interval_hours",
    "signal_chart","price_tick","qty_step","min_notional","quick_preset_id","quick_preset_revision","fee_source",
    "account_rules"}
POLICY_FIELDS = {"sizing_policy","fixed_qty","fixed_notional","equity_percent","risk_per_stop_percent",
    "stop_distance","max_abs_position_qty","max_notional","max_leverage","max_order_risk","max_active_orders",
    "max_cumulative_fees","max_drawdown_percent","daily_loss_limit","cooldown_events"}
REALISM_FIELDS = {"execution_model_revision","participation_rate","order_end_policy","bar_path_scenario"}


CONTINUOUS_SERIES_VARIANTS = frozenset({"native", "ohlcv"})
CONTINUOUS_VOLUME_SEMANTICS = frozenset({"base_asset", "shares"})


def _require_live_bars(key):
    """Refuse a source that declares no live bars at this interval (ADR-DATA-002 D2c).

    Twelve Data's US equities are history only: its WebSocket sends price
    ticks, not closed 1m bars. Other resolution failures (an exchange this
    process has not loaded) are left to the stream the run opens.
    """
    from app.data_engine.interval_resolution import (
        IntervalPurpose, IntervalResolutionError, IntervalResolutionErrorCode, IntervalResolver)
    from app.exchanges.registry import get_exchange_registry
    try:
        # The exchanges this process has loaded: bootstrapping them all here
        # would take seconds in a fresh worker.
        IntervalResolver(get_exchange_registry()).resolve(exchange=key.exchange, market_type=key.market_type,
                                                          interval=key.interval, purpose=IntervalPurpose.REALTIME)
    except IntervalResolutionError as failure:
        if failure.code in {IntervalResolutionErrorCode.PURPOSE_UNSUPPORTED,
                            IntervalResolutionErrorCode.KLINE_CHANNEL_UNAVAILABLE}:
            raise BacktestError("CONTINUOUS_LIVE_BARS_UNAVAILABLE",
                f"{key.exchange} has no live {key.interval} bars for this market; "
                "forward runs follow live bars, so this data source cannot run one") from None


def _fixed_interval(interval):
    from app.data_engine.interval_policy import IntervalAlignment, parse_interval_spec
    spec = parse_interval_spec(interval)
    return spec is not None and not spec.timezone and spec.alignment is not IntervalAlignment.CALENDAR_MONTH


def _refuse_external(execution, *, follow, bind_external):
    """B-333c: an external model's forward run reads its own bars on the plain bar account."""
    if follow:
        raise BacktestError("FIDELITY_UNSUPPORTED", "The chart follows builtin and Python strategies; run an external model forward instead")
    for name, feature in (("signal_chart", "a signal chart"), ("account_rules", "practice account rules"),
                          ("execution_model_revision", "execution realism")):
        if execution.get(name) is not None:
            raise BacktestError("FIDELITY_UNSUPPORTED",
                f"Forward runs of an external model read the run's own bars on the bar account, without {feature}")
    if bind_external is None:
        raise BacktestError("FIDELITY_UNSUPPORTED", "External models need this Host's external connections")


def prepare_definition(provider, execution, key: SeriesKey, *, warmup_bars=0, follow=False, calendar=None,
                       bind_external=None):
    """Own current code and normalized fees/account before acquiring any data.

    ``follow`` (ADR-BACKTEST-015 P4b): a FOLLOW run consumes the chart's own closed
    bars, so any fixed-length chart interval qualifies. A forward run does too
    (B-333): it advances on closed bars of its series' interval, whole minutes long.
    ``calendar`` is the series' trading calendar (ADR-DATA-002 D2c): forward
    runs do not cross market closures yet. ``bind_external`` binds an external
    model to its connected forward connection (B-333c).
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
    if not isinstance(key,SeriesKey) or not (_fixed_interval(key.interval) if follow else grid_interval(key.interval)):
        raise BacktestError("FIDELITY_UNSUPPORTED",
            "This continuous source requires a fixed-length interval of whole minutes, such as 1m, 5m, 1h or 1d")
    if not follow:
        # A forward run follows live closed bars (ADR-DATA-002 D2c). FOLLOW
        # reads the chart's stored bars and may follow a history-only source.
        _require_live_bars(key)
        if session_calendar(calendar) is not None:
            raise BacktestError("CONTINUOUS_MARKET_SESSIONS_UNSUPPORTED",
                "Forward runs need a market that trades around the clock; this market closes between sessions")
    # Capabilities and price semantics, not the asset class: raw prices and
    # base-unit volumes on a spot market, or on futures whose venue declares
    # base-quantity linear contract rules (ADR-DATA-002 D3c).
    if (key.market_type not in {"spot","futures"}
            or (key.market_type=="futures" and venue_role_contract(
                key.exchange,"futures",CONTRACT_RULES)!=BINANCE_USDM_LINEAR_BASE_QUANTITY)
            or key.identity.series_variant not in CONTINUOUS_SERIES_VARIANTS
            or key.identity.price_adjustment!="raw"
            or key.identity.volume_semantics not in CONTINUOUS_VOLUME_SEMANTICS):
        raise BacktestError("FIDELITY_UNSUPPORTED",
            "This continuous source requires raw spot OHLCV, or futures with base-quantity contract rules, "
            "with base-unit volume")
    # B-333b: refuse what no Pine forward run supports before compiling its code.
    from .continuous_pine import refuse_before_compile
    refuse_before_compile(provider, execution, follow=follow)
    provider = prepare_provider(provider)
    if provider["language"] == "external":
        _refuse_external(execution, follow=follow, bind_external=bind_external)
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
    if provider["language"] == "pine":
        from .continuous_pine import pine_definition_config
        config.update(pine_definition_config(provider, realism_enabled=realism.enabled))
    if provider["language"] == "external":
        # Last: every refusal above is answered before the connection is read.
        provider = {**provider, "external": bind_external(provider, config, warmup_bars=warmup_bars)}
    series = [key.exchange,key.market_type,key.symbol,key.interval,*key.identity.storage_values]
    return {"engine_version":ENGINE_VERSION,"language":provider["language"],"provider":provider,
        "configuration":config,"input_plan":{"roles":["BARS"]},
        "source_kind":"MARKET_BAR","source_series":series,
        "market":{"venue":key.exchange,"symbol":key.symbol}}
