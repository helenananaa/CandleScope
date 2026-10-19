import pine_compat
import pytest

from candlescope_plugin_pine_compat import external_strategy as adapter
from candlescope_plugin_pine_compat.strategy_time import engine_bars

pytestmark = pytest.mark.skipif(
    not hasattr(pine_compat.Program, "external_session"),
    reason="requires isolated incremental engine candidate",
)


def wire(source):
    return {
        "source": '//@version=6\nstrategy("external")\n' + source,
        "context": {"symbol": "BINANCE:BTCUSDT", "timeframe": "1"},
        "parameters": {},
    }


def data(i):
    bar = {
        "time": 1700000000 + i * 60, "open": 10 + i, "high": 11 + i, "low": 9 + i, "close": 10 + i, "volume": 1
    }
    account = {
        "time": bar["time"],
        "position_size": 0,
        "position_avg_price": None,
        "equity": 1000,
        "initial_capital": 1000,
        "netprofit": 0,
        "openprofit": 0,
    }
    return bar, account


def test_real_adapter_retains_native_state_and_rebases_corrections():
    request = wire(
        'var float total = 0\ntotal += close\nplot(total)\nplot(ta.sma(close,2))\nif close > 11\n    strategy.entry("L",strategy.long)'
    )
    bars, accounts = [], []
    native = None
    for i in range(6):
        bar, account = data(i)
        bars.append(bar)
        accounts.append(account)
        payload = (
            {**request, "bars": list(bars), "accounts": list(accounts)}
            if i == 0
            else {
                "operation": "append_prefix",
                "prefix_base": i,
                "bars": [bar],
                "accounts": [account],
            }
        )
        result = adapter.execute(payload)
        assert adapter._session.cursor == i + 1
        if native is None:
            native = adapter._session
        assert adapter._session is native
        baseline = pine_compat.compile_script(request["source"]).run_external(
            engine_bars(bars),
            [{**frame, "time": frame["time"] * 1000} for frame in accounts],
            chart_symbol=request["context"]["symbol"],
            chart_timeframe="1",
        )
        assert result["raw_output"] == baseline["output"]
        assert result["intents"] == baseline["intents"]
    bars[0] = {**bars[0], "close": 10.5}
    adapter.execute({**request, "bars": bars, "accounts": accounts})
    assert adapter._session is not native


@pytest.mark.parametrize(
    "expression", ["barstate.islast ? close : na", "last_bar_index", "last_bar_time"]
)
def test_dataset_endpoint_dependencies_keep_prefix_replay_semantics(expression):
    request = wire("plot(" + expression + ")")
    bar, account = data(0)
    adapter.execute({**request, "bars": [bar], "accounts": [account]})
    bar, account = data(1)
    result = adapter.execute(
        {"operation": "append_prefix", "prefix_base": 1, "bars": [bar], "accounts": [account]}
    )
    assert adapter._session is None
    if expression == "last_bar_index":
        assert result["raw_output"]["plots"][0]["values"] == [1, 1]
