"""Both Pine input paths share one dispatch and the captured replay boundary."""
import asyncio
from dataclasses import replace
from types import SimpleNamespace

from app.indicator.pine_host import PineHostInputs
from app.indicator.runtime_routes import IndicatorRuntimeRoute, IndicatorRuntimeRoutes
from app.indicator.runtime_service import IndicatorRuntimeService
from tests.test_indicator_runtime_service import _Host, _descriptor
from tests.test_pine_host_completion import Host as Compiler, bar, request


def test_extended_environment_is_prepared_once_and_clipped_to_replay(monkeypatch):
    monkeypatch.setattr("app.indicator.pine_host.symbol_metadata", lambda *args: None)
    calls = []
    class Host(_Host, Compiler):
        pass
    def query(*args, **kwargs):
        calls.append(kwargs)
        # Deliberately over-return, including a closed row beyond the cursor.
        return SimpleNamespace(bars=[bar(-1), bar(0), bar(1, False), bar(2)], missing_ranges=[], history_state="ready")
    manager = SimpleNamespace(query=query)
    boundary = bar(1).time * 1000 + 20_000
    async def run():
        host = Host(runtime_descriptor=_descriptor(languages=("pine",)))
        service = IndicatorRuntimeService(IndicatorRuntimeRoutes((
            IndicatorRuntimeRoute("pine", "sidecar", "fixture.runtime"),)), host=host)
        service.prepare_inputs = PineHostInputs(lambda: manager).prepare
        service.pine_data_manager = lambda: manager
        async def legacy():
            raise AssertionError("Pine sidecar cannot use legacy execution")
        raw = request(params={"__pineHost": {"libraries": {}}}, options={"pineRevealedBoundaryMs": boundary})
        result = await service.execute(raw, legacy=legacy, adapt_sidecar=lambda result: {"ok": result.ok})
        assert result == {"ok": True}
        assert len(calls) == 1
        assert calls[0]["end_ms"] <= boundary and calls[0]["auto_backfill"] is False
        sent = host.requests[0][1]
        inputs = sent.options["pineHost"]
        assert inputs["executionTimes"][-1] == boundary
        assert sent.options["pineExecutionTimeMs"] == inputs["executionTimes"]
        assert inputs["contexts"][0]["forming"] is False
        assert [row["time"] for row in inputs["contexts"][0]["bars"]] == [bar(-1).time, bar(0).time]
        await service.stop()
    asyncio.run(run())


def test_existing_pine_libraries_and_contexts_keep_the_local_data_path():
    async def run():
        params = {"__pineLibraries": {"test/Math/1": "library source"},
                  "__pineContexts": [{"symbol": "BINANCE:ETHUSDT", "timeframe": "1"}],
                  "__pineAlerts": True, "__pineSessionEpoch": "2"}
        host = SimpleNamespace()  # No eager compilation or provider query on this path.
        prepared, failure = await PineHostInputs(lambda: None).prepare(replace(request(), params=params), host, "pine")
        assert failure is None
        sdk = prepared.to_sdk_request()
        assert sdk.options["pineLibrarySources"] == params["__pineLibraries"]
        assert sdk.options["pineRequestContexts"] == params["__pineContexts"]
        assert sdk.options["pineAlerts"] is True and sdk.options["pineSessionEpoch"] == "2"
        assert not sdk.options.get("pineHostPrepared")
    asyncio.run(run())
