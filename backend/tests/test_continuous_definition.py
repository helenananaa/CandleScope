"""Creation preflight with the real Manager/frozen-input/account pipeline."""
from dataclasses import asdict,replace
import json

import pytest

from app.backtest.continuous_bar_host import ContinuousBarHost
from app.backtest.continuous_bar_source import ContinuousMarketBarSource
from app.backtest.continuous_definition import prepare_definition
from app.backtest.continuous_provider import ContinuousProviderFactory
from app.backtest.errors import BacktestError
from app.backtest.identity import canonical_json
from app.backtest.service import BacktestService
from app.backtest.strategy.builtin import BUILTIN_SMA_REVISION
from app.data_engine.data_manager.models import SeriesKey
from app.data_engine.data_manager import DataManager
from app.data_engine.storage import klines_repo
from app.data_engine.series_identity import KlineSeriesIdentity
from app.local_data.service import LocalDatasetService
from app.market_dataset.snapshot import MarketEvent
from tests.test_backtest_control_plane import _settings,_payload
from tests.test_continuous_provider import spec
from tests.test_continuous_bar_source import create_frozen
from tests.test_continuous_bar_host import prepare
from tests.test_continuous_guarded_source import START,END,STEP,SOURCE,_row
from tests.test_kline_revision_contract import storage as storage

KEY=SeriesKey("BTCUSDT","1m",market_type="futures")


@pytest.mark.parametrize("python",[False,True])
@pytest.mark.parametrize("market",["spot","futures"])
def test_creation_preflight_executes_exact_frozen_source_then_tail(storage,tmp_path,monkeypatch,python,market):
    service,row,_,_,store=prepare(tmp_path,monkeypatch)
    key=replace(KEY,market_type=market)
    account="SPOT_CASH_V1" if market=="spot" else "LINEAR_PERP_ONE_WAY_V1"
    if market=="spot":
        row=service.create_run(_payload(account_model=account,market_type=market,parameters={"fast":3,"slow":5},
            warmup_bars=3,taker_fee_bps="3",maker_fee_bps="1"),idempotency_key="spot-reference",now_ms=2)
    manager=DataManager();manager.set_storage(storage)
    klines_repo.upsert_klines(key.symbol,key.interval,[_row(START+i*STEP,100+i%7) for i in range(25)],
        market_type=key.market_type,source=SOURCE)
    source=ContinuousMarketBarSource(manager,LocalDatasetService(tmp_path/'local-data'),key,clock_ms=lambda:END+1)
    receipt=source.register("cs_source",from_ms=START)
    definition=prepare_definition(spec(python=python),{"account_model":account,"taker_fee_bps":"3","maker_fee_bps":"1"},key,warmup_bars=3)
    factory=ContinuousProviderFactory(scratch_root=tmp_path)
    host=None
    try:
        definition=create_frozen(source,receipt,definition,factory,store)
        host=ContinuousBarHost.resume(store,"cs_source",factory)
        while host.row["event_time_ms"]<END:
            batch=source.acquire(host,revealed_through_ms=END,limit=7)
            batch.apply(host,manager)
        actual=asdict(host.kernel.run((),host._observe,finalize=True))
        rows=source._query_rows(START,END,host.source_receipt.storage_revision)
        events=tuple(MarketEvent(i+1,r["close_time_ms"],"BARS",r) for i,r in enumerate(rows))
        reference=service.execute_bar_run(row["run_id"],events=events,provider=factory(definition),
            observation_market=definition["market"],now_ms=3)["result"]
        for name in ("decision_hash","fill_hash","ledger_hash","orders","fills","ledger","equity_curve"):
            assert canonical_json(actual[name])==canonical_json(reference[name]),name
        assert actual["fills"] and host.row["phase"]=="LIVE"
        assert definition["source_series"]==list(receipt.series)
        assert definition["configuration"]["funding_mode"]=="OFF"
        assert set(definition["input_plan"])=={"roles"}
    finally:
        if host is not None:host.close()
        source.close();store.close();service.shutdown()


@pytest.mark.parametrize("execution",[
    {"initial_balance":"0"},{"slippage_bps":"-1"},{"taker_fee_bps":"-1"},
    {"maker_fee_bps":"NaN"},{"price_tick":"0"},{"qty_step":"-0.1"},
    {"account_model":"LINEAR_PERP_ONE_WAY_V2"},
    {"account_model":"SPOT_CASH_V1"},{"leverage":"2"},
    {"funding_mode":"HISTORICAL_REQUIRED"},{"funding_rate":"0.0001"},
    {"contract_data_mode":"HISTORICAL_CONTRACT_V1"},{"gap_policy":"SKIP_WITH_WARNING"},
    {"strategy_revision_id":"fake"},{"snapshot_hash":"fake"},{"python_execution_protocol":"MARKET_BATCH_V1"},
    {"participation_rate":"0.1"},{"latency_ms":5},
    {"execution_model_revision":"unknown"},
    {"execution_model_revision":"EXECUTION_REALISM_V2","participation_rate":"0"},
    {"max_abs_position_qty":"5"},{"sizing_policy":"FIXED_QTY_V1"},
    {"quick_preset_id":"unconfirmed"},{"funding_interval_hours":1.5},
    {"cooldown_events":True},{"max_active_orders":"2"},
])
def test_financial_or_unqualified_input_rejected_before_resources(tmp_path,execution):
    with pytest.raises(BacktestError):prepare_definition(spec(),execution,KEY)
    assert list(tmp_path.iterdir())==[]


@pytest.mark.parametrize("warmup",[-1,True,200001,"3"])
def test_warmup_is_exact_closed_bar_count(warmup):
    with pytest.raises(BacktestError):prepare_definition(spec(),{},KEY,warmup_bars=warmup)


@pytest.mark.parametrize("key",[
    SeriesKey("BTCUSDT","5m"),SeriesKey("BTCUSD_PERP","1m",market_type="coinm"),
    SeriesKey.create("BTCUSDT","1m",identity=KlineSeriesIdentity("vendor","binance",volume_semantics="contracts")),
    SeriesKey.create("BTCUSDT","1m",identity=KlineSeriesIdentity("vendor","binance",price_adjustment="adjusted")),
])
def test_unqualified_source_dimensions_not_relabelled(key):
    with pytest.raises(BacktestError):prepare_definition(spec(),{},key)


def test_spot_account_and_semantic_identity_are_explicit():
    key=SeriesKey.create("BTCUSDT","1m",market_type="spot",identity=KlineSeriesIdentity("vendor","binance"))
    value=prepare_definition(spec(),{"account_model":"SPOT_CASH_V1"},key)
    assert value["configuration"]["market_type"]=="spot"
    assert value["configuration"]["account_model"]=="SPOT_CASH_V1"
    assert value["source_series"]==[key.exchange,"spot",key.symbol,"1m",*key.identity.storage_values]
    with pytest.raises(BacktestError):prepare_definition(spec(),{},key)


def test_shared_financial_rules_match_fixed_run_configuration(tmp_path):
    service=BacktestService.start(_settings(tmp_path),now_ms=1,enforce_registered_revisions=True)
    execution={"initial_balance":"12345.67","slippage_bps":"2","taker_fee_bps":"3.2","maker_fee_bps":"1",
        "price_tick":"0.01","qty_step":"0.001","min_notional":"5","sizing_policy":"FIXED_QTY_V1","fixed_qty":"2",
        "max_abs_position_qty":"4","execution_model_revision":"EXECUTION_REALISM_V2","participation_rate":"0.2",
        "quick_preset_id":"confirmed","quick_preset_revision":"r1","fee_source":"user"}
    try:
        prepared=prepare_definition(spec(),execution,KEY,warmup_bars=3)
        account,config,_=service._execution_from_payload({**execution,"strategy_revision_id":BUILTIN_SMA_REVISION,
            "market_type":KEY.market_type,"output_mode":"TARGET_POSITION"},fidelity="BAR_APPROX",
            parameters_json=json.dumps({"fast":3,"slow":5}),warmup_bars=3)
        for name in (*execution,"host_policy_revision","risk_policy","fill_policy","equity_curve_event_interval"):
            assert prepared["configuration"][name]==config[name],name
        assert prepared["configuration"]["account_model"]==account
        assert service.repository.list_runs()==[] and service.repository.list_strategy_revisions()==[]
    finally:service.shutdown()
