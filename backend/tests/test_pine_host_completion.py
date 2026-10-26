import asyncio
from dataclasses import replace
from types import SimpleNamespace

from candlescope_plugin_sdk import AnalyzeResult, ExecuteBatchResult, RenderOutput
from app.indicator.pine_host import PineHostInputs, compiled_contexts, pine_timeframe, symbol_metadata
from app.indicator.runtime_service import IndicatorRuntimeRequest
from app.data_engine.data_manager.models import BarData, QueryResult
from app.alerts.facade import AlertFacade
from app.indicator.pine_alerts import PineAlerts


def bar(index, closed=True):
    return BarData(time=1700000040 + index * 60, open=10, high=20, low=5, close=15, volume=100, is_closed=closed)


def request(**kwargs):
    return IndicatorRuntimeRequest(language="pine", source='//@version=6\nindicator("host")\nplot(request.security("BINANCE:ETHUSDT","1",close))',
        exchange="binance", market_type="spot", symbol="BTCUSDT", interval="1m", bars=(bar(0), bar(1, False)), **kwargs)


REQUIREMENTS = {"requests": [{"symbol": {"kind": "literal", "value": "BINANCE:ETHUSDT"}, "timeframe": {"kind": "literal", "value": "1"}}],
                "execution": {"clock": "explicitTimestampWhenEvaluated"}}


class Host:
    async def analyze(self, runtime_id, payload):
        assert payload.options["pineHost"]["libraries"] == {}
        return AnalyzeResult(ok=True, executable=True, meta={"hostRequirements": REQUIREMENTS,
            "hostBindings": {"chartSymbol": "BINANCE:BTCUSDT", "chartTimeframe": "1"}})


def test_host_queries_warmup_binds_clocks_and_releases_realtime_dependencies(monkeypatch):
    monkeypatch.setattr("app.indicator.pine_host.symbol_metadata", lambda *args: {"minMove": 1, "priceScale": 100})
    calls, opened, released = [], [], []
    class Data:
        async def ensure_stream(self, **kwargs): opened.append(kwargs)
        async def release_stream(self, **kwargs): released.append(kwargs)
        def query(self, symbol, interval, **kwargs):
            calls.append((symbol, interval, kwargs))
            return QueryResult(bars=[bar(-1), bar(0), bar(1, False)])
    async def run():
        inputs = PineHostInputs(lambda: Data())
        raw = request(params={"__pineHost": {"libraries": {}}, "__pineAlerts": True},
            options={"pineLeaseId": "owner"}, transport="websocket.snapshot")
        for _ in range(2):
            prepared, failure = await inputs.prepare(raw, Host(), "pine")
            assert failure is None
            assert prepared.params == {}
            host = prepared.options["pineHost"]
            assert host["executionTimes"][0] == bar(1).time * 1000 - 1
            assert host["contexts"][0]["forming"] is True
            assert host["symbolMetadata"]["BINANCE:ETHUSDT"]["priceScale"] == 100
            assert prepared.options["pineAlerts"]
        assert len(opened) == 1
        assert calls[0][2]["start_ms"] == bar(-1).time * 1000
        assert prepared.options["pineAlertInputs"] == {"libraries": {}}
        class EmptyHost:
            async def analyze(self, *_args):
                return AnalyzeResult(ok=True, executable=True)
        await inputs.prepare(replace(raw, source='//@version=6\nindicator("simple")\nplot(close)'), EmptyHost(), "pine")
        assert released == opened and not inputs.leases
        await inputs.release("owner")
        assert released == opened and not inputs.leases
    asyncio.run(run())


def test_partial_provider_history_is_not_silently_executed(monkeypatch):
    monkeypatch.setattr("app.indicator.pine_host.symbol_metadata", lambda *args: None)
    async def run():
        manager = SimpleNamespace(query=lambda *a, **kw: SimpleNamespace(bars=[bar(0)], missing_ranges=[{}], history_state="pending"))
        _, failure = await PineHostInputs(lambda: manager).prepare(request(params={"__pineHost": {"libraries": {}}}), Host(), "pine")
        assert failure.diagnostics[0].code == "PINE_REQUEST_DATA_PENDING"
    asyncio.run(run())


def test_compiled_inventory_expands_nested_context_and_rejects_unbound_dynamic():
    import pytest
    import copy
    requirements = {"requests": [*copy.deepcopy(REQUIREMENTS["requests"]),
        {"symbol": {"kind": "currentContextSymbol"}, "timeframe": {"kind": "literal", "value": "5"}}]}
    assert compiled_contexts(requirements, "BINANCE:BTCUSDT", "1") == [
        ("BINANCE:ETHUSDT", "1"), ("BINANCE:BTCUSDT", "5"), ("BINANCE:ETHUSDT", "5")]
    requirements["requests"][0]["symbol"] = {"kind": "runtimeExpression"}
    with pytest.raises(ValueError, match="PINE_DYNAMIC_CONTEXT_REQUIRED"):
        compiled_contexts(requirements, "A", "1")
    assert pine_timeframe("1h") == "60"
    assert pine_timeframe("1M") == "1M"


def test_instrument_binding_preserves_exact_grid_and_does_not_invent_inverse_support(monkeypatch):
    import pytest
    monkeypatch.setattr("app.indicator.pine_host.get_cached_symbol_metadata", lambda *args: {
        "priceTickSize": "0.25", "quantityStep": "0.003", "minQuantity": "0.009", "contractMultiplier": "10", "quoteAsset": "USDT"})
    assert symbol_metadata("binance", "usdm", "A") == {"minMove": 1, "priceScale": 4,
        "quantityStep": "0.003", "minContract": "0.009", "pointValue": 10, "currency": "USDT"}
    with pytest.raises(ValueError, match="INVERSE_CONTRACT"):
        symbol_metadata("binance", "coinm", "A")


def test_alerts_suppress_seed_preview_and_replay_and_deduplicate_after_restart(tmp_path):
    async def run():
        facade = AlertFacade(store_path=tmp_path / "alerts.json")
        observer = PineAlerts(lambda: facade)
        raw = request(options={"pineAlerts": True, "pineLiveUpdate": True, "pineLiveBarTime": bar(1).time}, transport="websocket.snapshot")
        events = [{"id": 1, "time": bar(0).time * 1000, "message": "old"},
                  {"id": 1, "time": bar(1).time * 1000, "message": "closed"}]
        result = ExecuteBatchResult(ok=True, output=RenderOutput(), meta={"pineAlerts": events, "sessionReset": True})
        await observer.observe(raw, result)
        assert not facade.list_history()
        result.meta["sessionReset"] = False
        await observer.observe(raw, result)  # forming event is not confirmed
        assert not facade.list_history()
        closed = replace(raw, bars=(bar(0), bar(1)))
        await observer.observe(closed, result)
        assert len(facade.list_history()) == 1
        restored = AlertFacade(store_path=tmp_path / "alerts.json")
        await PineAlerts(lambda: restored).observe(closed, result)
        assert len(restored.list_history()) == 1
        await observer.observe(replace(closed, transport="http.range"), result)
        assert len(facade.list_history()) == 1
        assert facade.list_rules()[0]["triggerCount"] == 1
        assert facade.list_history()[0]["message"] == "closed"
        rule = facade.list_rules()[0]
        rule["expression"] = {"left": "close", "comparator": ">", "right": {"type": "number", "value": 1000}}
        facade.save_rule(rule)
        result.meta["pineAlerts"].append({"id": 2, "time": bar(1).time * 1000, "message": "should not send"})
        await observer.observe(closed, result)
        assert len(facade.list_history()) == 1 and result.meta["pineAlertStatus"] == "modified"
    asyncio.run(run())
