from datetime import datetime, timezone

import pytest

from app.data_preparation.models import PreparationError
from app.data_preparation.native_plan import chart_interval, plan_inputs, requested_contexts
from app.data_preparation.native_lookback import expression_lookback
from tests.test_data_preparation import async_test, bars, terminal, START


def test_security_discovery_ignores_comments_and_string_contents():
    source = '''// request.security("FAKE", "1", close)
text = 'request.security("ALSO_FAKE", "1", close)'
/* request.security("COMMENT", "1", close) */
a = request.security("BINANCE:ETHUSDT", "60", ta.sma(close, 10))
b = request.security_lower_tf(syminfo.tickerid, "1", close)
c = request.security("", timeframe.period, close)
'''
    assert requested_contexts(source, symbol="BINANCE:BTCUSDT", interval="5m") == [
        ("BINANCE:ETHUSDT", "60"), ("BINANCE:BTCUSDT", "1"), ("BINANCE:BTCUSDT", "5")]
    with pytest.raises(PreparationError, match="Declare"):
        requested_contexts('request.security(symbolInput, "60", close)', symbol="BTCUSDT", interval="5m")
    with pytest.raises(PreparationError, match="invalid string literal"):
        requested_contexts(r'request.security("\uZZZZ", "60", close)', symbol="BTCUSDT", interval="5m")


def test_dependency_grid_shares_minute_download_and_keeps_previous_calendar_bar():
    start = int(datetime(2024, 3, 1, tzinfo=timezone.utc).timestamp() * 1000)
    february = int(datetime(2024, 2, 1, tzinfo=timezone.utc).timestamp() * 1000)
    context = dict(exchange="binance", market_type="spot", symbol="BTCUSDT", interval="5m",
                   start_time_ms=start, end_time_ms=start + 86_400_000 - 1)
    requirements, bindings = plan_inputs(context, [
        {**context, "interval": "60m"}, {**context, "interval": "1M"},
        {**context, "symbol": "ETHUSDT", "interval": "1h"}])
    assert len(requirements) == 2
    assert requirements[0].start_ms == february
    assert requirements[0].end_ms == start + 86_400_000
    assert bindings[1]["interval"] == "1h"
    assert bindings[2]["end_time_ms"] == start - 1
    assert requirements[1].start_ms == start - 3_600_000


@pytest.mark.parametrize("value,expected", [("60", "1h"), ("D", "1d"), ("W", "1w"), ("M", "1M")])
def test_native_timeframe_keeps_calendar_semantics(value, expected):
    assert chart_interval(value) == expected


def test_subminute_dependencies_are_not_silently_upsampled():
    with pytest.raises(PreparationError):
        chart_interval("30S")


@pytest.mark.parametrize("expression,prior", [
    ("close", 0), ("close[5]", 5), ("ta.sma(close, 10)", 9),
    ("ta.sma(ta.sma(close, 3), 4)", 5), ("ta.highest(20)", 19),
    ("ta.sma(close[2], length=10)", 11), ("ta.crossover(ta.sma(close, 10), close)", 10),
    ("lambda: ta.sma(close, 2 * 5)", 9), ("ta.ema(close, 10)", None),
    ("customIndicator(close)", None), ("ta.sma(close, userLength)", None),
    ("ta.sma(close, 10, unknownSeries)", None),
])
def test_finite_requested_expression_history_and_unknown_boundaries(expression, prior):
    assert expression_lookback(expression) == prior


def test_requested_history_bound_and_calendar_warmup():
    with pytest.raises(PreparationError, match="5000"):
        expression_lookback("close[5001]")
    start = int(datetime(2024, 3, 1, tzinfo=timezone.utc).timestamp() * 1000)
    context = dict(exchange="binance", market_type="spot", symbol="BTCUSDT", interval="5m",
        start_time_ms=start, end_time_ms=start + 86_400_000 - 1)
    requirements, bindings = plan_inputs(context, [{**context, "interval": "1M", "warmup_bars": 3}])
    assert bindings[0]["start_time_ms"] == start
    assert requirements[0].start_ms == int(datetime(2023, 12, 1, tzinfo=timezone.utc).timestamp() * 1000)


@async_test
@pytest.mark.parametrize("expression,prior,declared", [("close", 1, None), ("ta.sma(close, 10)", 10, None),
    ("ta.sma(ta.sma(close, 3), 4)", 6, None), ("ta.ema(close, 10)", 20, 20)])
async def test_native_api_freezes_multiple_symbols_and_timeframes_before_launch(tmp_path, expression, prior, declared):
    import httpx
    from fastapi import FastAPI
    from app.api.v1.data_preparation import router
    from app.data_preparation.bar_adapter import BarPreparationAdapter
    from app.data_preparation.repository import PreparationRepository
    from app.data_preparation.service import PreparationService
    from tests.test_backtest_chart_context import _runtime

    runtime = _runtime(tmp_path)
    inventory, acquired, launched = {}, [], []

    class Coordinator:
        async def request_and_wait(self, repair):
            acquired.append(repair.symbol)
            inventory.setdefault(repair.symbol, []).extend(
                {**bars()[0], "open_time": timestamp, "close_time": timestamp + 59_999}
                for timestamp in range(repair.start_ms, repair.end_ms + 1, 60_000))

    identity = {"protocol": "candlescope.native-strategy/1", "engine": {"package": "test-pine", "version": "test"}}

    def runner(plugin, wire, **kwargs):
        # Only the plugin process is controlled; real native freezing, durable
        # run creation, idempotency and account-authority checks remain active.
        if wire.get("operation") == "describe":
            return {"identity": identity}
        launched.append(wire)
        return {"identity": identity, "execution_mode": "NATIVE", "account_authority": "pine-compat-runtime"}

    runtime.native.resolver = lambda language: {"plugin_id": "candlescope.pine-compat", "command": ["fixture"]}
    runtime.native.runner = runner
    adapter = BarPreparationAdapter(tmp_path / "chunks", coordinator=Coordinator(),
        local_data=runtime.local_data, backtest_runtime=runtime,
        query=lambda symbol, *args, **kw: [row for row in inventory.get(symbol, [])
            if kw["start_ms"] <= row["open_time"] <= kw["end_ms"]])
    service = PreparationService(PreparationRepository(tmp_path / "jobs.db"), adapter)
    app = FastAPI()
    app.state.data_preparation_service, app.state.backtest_runtime = service, runtime
    app.include_router(router)
    await service.start()
    try:
        body = {"idempotency_key": "native-context-001", "language": "pine", "parameters": {},
            "source": f'strategy("Dependencies")\na = request.security("BINANCE:ETHUSDT", "60", {expression})\nb = request.security(syminfo.tickerid, "60", close)',
            "context": {"exchange": "binance", "market_type": "futures", "symbol": "BTCUSDT",
                "interval": "5m", "range_mode": "CUSTOM", "fidelity_preference": "FAST",
                "start_time_ms": START, "end_time_ms": START + 3_600_000 - 1}}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            if declared is not None:
                rejected = await client.post("/data-preparations/native-strategy", json=body)
                assert rejected.status_code == 409
                assert rejected.json()["detail"]["code"] == "DEPENDENCY_WARMUP_REQUIRED"
                assert acquired == []
                body["contexts"] = [{"exchange": "binance", "market_type": "futures", "symbol": "ETHUSDT",
                    "interval": "1h", "warmup_bars": declared}]
            response = await client.post("/data-preparations/native-strategy", json=body)
            assert response.status_code == 202, response.text
            job = await terminal(service, response.json()["id"])
            assert job["state"] == "READY", job["error"]
            repeated = await client.post("/data-preparations/native-strategy", json=body)
            assert repeated.json()["id"] == job["id"]
        import asyncio
        from app.data_preparation.models import PreparationRequest
        run_id = job["result"]["native_run"]["run_id"]
        for _ in range(100):
            run = runtime.native.get(run_id)
            if run["state"] in {"COMPLETED", "FAILED"}:
                break
            await asyncio.sleep(0.01)
        assert run["state"] == "COMPLETED", run
        resumed = await adapter.launch(PreparationRequest.model_validate(job["request"]), job["result"], job["id"])
        assert resumed["native_run"]["run_id"] == run_id
        assert len(runtime.native.list()) == len(launched) == 1
        assert runtime.service.list_runs() == []
        payload = run["config"]
        assert run["execution_mode"] == "NATIVE"
        assert payload["interval"] == "5m"
        assert {(item["symbol"], item["timeframe"]) for item in payload["contexts"]} == {
            ("BINANCE:ETHUSDT", "60"), ("BINANCE:BTCUSDT", "60")}
        assert set(acquired) == {"BTCUSDT", "ETHUSDT"}
        assert len(job["request"]["requirements"]) == 2
        eth = next(item for item in launched[0]["contexts"] if item["symbol"] == "BINANCE:ETHUSDT")
        assert eth["bars"][0]["time"] * 1000 == START - prior * 3_600_000
        assert len(eth["bars"]) == prior + 1
        assert launched[0]["bars"][0]["time"] * 1000 == START
    finally:
        await service.shutdown()
        runtime.shutdown()
