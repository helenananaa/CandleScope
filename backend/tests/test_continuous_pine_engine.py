"""Pine forward runs (B-333b) on the installed Pine runtime equal the fixed Host run.

The reference is ``service.execute_bar_run`` of a PINE_ENGINE revision with the same
source and configuration. CI runs it in pine-host-contracts (``qualify_host_contracts.py``).
"""
from dataclasses import asdict
import json
import os

import pytest

from app.backtest.continuous_bar_host import ContinuousBarHost
from app.backtest.continuous_definition import prepare_definition
from app.backtest.continuous_provider import ContinuousProviderFactory, prepare_provider
from app.backtest.continuous_store import ContinuousStrategyStore
from app.backtest.errors import BacktestError
from app.backtest.identity import canonical_json
from app.backtest.models import ENGINE_VERSION
from app.backtest.service import BacktestService
from app.backtest.strategy.pine_engine import PineEngineProvider
from tests.test_backtest_control_plane import _payload, _settings
from tests.test_continuous_bar_host import apply
from tests.test_continuous_definition import KEY
from tests.test_strategy_bar_continuation import events

pytestmark = pytest.mark.skipif(
    not os.environ.get("NATIVE_TEST_PINE_PYTHON"),
    reason="requires installed source-candidate Pine adapter",
)
MARKET = {"venue": "binance", "symbol": "BTCUSDT"}
SOURCE = """//@version=6
strategy("Forward", pyramiding=2)
fast = ta.sma(close, 3)
slow = ta.sma(close, 5)
if ta.crossover(fast, slow)
    strategy.entry("L", strategy.long, qty=2)
if ta.crossunder(fast, slow)
    strategy.close("L")
if bar_index % 6 == 0
    strategy.entry("S", strategy.short, qty=1, limit=close + 2)
strategy.exit("XS", "S", profit=6, loss=6)
"""


def test_forward_pine_run_restarts_and_equals_the_fixed_host_run(tmp_path, monkeypatch, qualified_pine):
    monkeypatch.setenv("BACKTEST_COLOCATED_BAR_ENABLED", "0")
    # A registered PINE_ENGINE revision, smoked, freezes its envelope into the run.
    service = BacktestService.start(_settings(tmp_path), now_ms=1, enforce_registered_revisions=True)
    store = ContinuousStrategyStore(tmp_path / "continuous.db")
    revision = service.create_strategy_revision({"language": "PINE_ENGINE", "name": "Forward", "source_text": SOURCE})
    payload = _payload(strategy_revision_id=revision["revision_id"], output_mode="ORDER_INTENT", source_event_kind="BAR",
        parameters={}, warmup_bars=3, taker_fee_bps="3", maker_fee_bps="1", slippage_bps="1", exchange="binance",
        market_type="usdm", symbol="BTCUSDT", interval="1m", account_model="LINEAR_PERP_ONE_WAY_V1",
        initial_balance="10000", price_tick="0.5", start_time_ms=0, end_time_ms=25 * 60_000)
    service.smoke_strategy_revision(str(revision["revision_id"]), payload, now_ms=2)
    row = service.create_run(payload, idempotency_key="pine-reference", now_ms=3)
    config = json.loads(row["config_json"])
    base = {"engine_version": ENGINE_VERSION}
    prepared = prepare_provider({"language": "pine", "source_text": SOURCE, "output_mode": "ORDER_INTENT"})
    # The forward compilation is the revision's: same envelope, same Pine identity.
    assert prepared["pine"] == {"execution_source": config["strategy_source"],
                                "dependency_hash": config["pine_runtime_identity"]}
    definition = {**base, "language": "pine", "provider": prepared, "market": MARKET, "input_plan": {"roles": ["BARS"]},
                  "configuration": {key: value for key, value in config.items()
                                    if key not in {"strategy_source", "output_mode", "parameters"}}}
    factory = ContinuousProviderFactory()
    host = None
    try:
        ContinuousBarHost.create_run(store, "cs_pine", definition=definition, mode="HISTORY_LIVE",
                                     data_revision="r1", event_time_ms=0, provider_factory=factory)
        host = ContinuousBarHost.resume(store, "cs_pine", factory)
        apply(host, events()[:11])
        host.close()
        store.close()
        # A fresh store and Pine worker continue the same account from the checkpoint.
        store = ContinuousStrategyStore(tmp_path / "continuous.db")
        host = ContinuousBarHost.resume(store, "cs_pine", factory)
        assert host.row["sequence"] == 11
        apply(host, events()[11:20])
        apply(host, events()[20:], caught_up=True)
        actual = asdict(host.kernel.run((), host._observe, finalize=True))
        reference = service.execute_bar_run(row["run_id"], events=events(), provider=PineEngineProvider(),
                                            now_ms=4, observation_market=MARKET)["result"]
        for key in ["decision_hash", "fill_hash", "ledger_hash", "fills", "ledger", "orders", "equity_curve"]:
            assert canonical_json(actual[key]) == canonical_json(reference[key]), key
        assert actual["fills"] and store.summary("cs_pine")["sequence"] == 25
        # Script entries, limit entries and the OCO exit bracket all reach the Host matcher.
        assert {("MARKET", "FILLED"), ("LIMIT", "FILLED"), ("STOP", "FILLED"), ("LIMIT", "CANCELLED_OCO")} <= {
            (order["type"], order["status"]) for order in actual["orders"]}
        assert host.planner.report()["pine_orders"] == reference["pine_orders"]
    finally:
        if host is not None:
            host.close()
        store.close()
        service.shutdown()


@pytest.mark.parametrize("declaration,named", [
    ("calc_on_order_fills=true", "calc_on_order_fills"),
    ("process_orders_on_close=true", "process_orders_on_close"),
])
def test_installed_runtime_refuses_scripts_outside_the_forward_subset(declaration, named, qualified_pine):
    source = SOURCE.replace('strategy("Forward", pyramiding=2)', f'strategy("Forward", pyramiding=2, {declaration})')
    with pytest.raises(BacktestError, match=named):
        prepare_definition({"language": "pine", "source_text": source, "output_mode": "ORDER_INTENT"},
                           {"account_model": "LINEAR_PERP_ONE_WAY_V1"}, KEY)
