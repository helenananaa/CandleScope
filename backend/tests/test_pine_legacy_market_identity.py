"""Legacy frozen inputs and failed preparation requests keep their identities."""

import asyncio
import os

import pytest

from app.data_preparation.bar_adapter import BarPreparationAdapter
from app.data_preparation.models import PreparationRequest, Requirement
from app.data_preparation.repository import PreparationRepository
from app.data_preparation.service import PreparationService
from tests.test_backtest_chart_context import _runtime, _bar, _request, _NoHostReads
from tests.test_data_preparation import START, async_test, terminal
from tests.test_native_strategy_plugins import plugin


@pytest.mark.parametrize(
    "market", ["usdm", "coinm", "linear_perpetual", "perpetual", "swap"]
)
def test_legacy_frozen_market_alias_is_resolved_without_rewriting(tmp_path, market):
    runtime = _runtime(tmp_path)
    try:
        manifest = runtime.local_data.freeze_host_bars(
            [_bar(0), _bar(1), _bar(2)],
            dataset_id="local-11111111111111111111111111111111",
            name="legacy alias fixture",
            exchange="binance",
            market_type=market,
            symbol="BTCUSDT",
            interval="1m",
            chart_context_hash="sha256:legacy-fixture",
        )
        directory = runtime.local_data.root / manifest["dataset_id"]
        before = {
            str(p.relative_to(directory)): p.read_bytes()
            for p in directory.rglob("*")
            if p.is_file()
        }
        ready = runtime.chart_context.resolve(
            _request(), host_data_manager=_NoHostReads()
        )
        assert ready["status"] == "READY"
        assert ready["dataset_id"] == manifest["dataset_id"]
        assert ready["data_epoch"] == manifest["data_epoch"]
        assert ready["request"]["market_type"] == "futures"
        assert (
            runtime.chart_context.resolve(_request(market_type="spot"))["status"]
            == "UNAVAILABLE"
        )
        assert before == {
            str(p.relative_to(directory)): p.read_bytes()
            for p in directory.rglob("*")
            if p.is_file()
        }
    finally:
        runtime.shutdown()


@async_test
@pytest.mark.skipif(
    not os.environ.get("NATIVE_TEST_PYTHON"), reason="requires installed Pine worker"
)
async def test_failed_legacy_alias_preparation_retries_unchanged_after_restart(
    tmp_path, monkeypatch
):
    runtime = _runtime(tmp_path)
    runtime.native.resolver = plugin
    rows = [
        dict(
            open_time=stamp,
            close_time=stamp + 59999,
            open=10,
            high=11,
            low=9,
            close=10,
            volume=100,
            source="backfill_rest_verified",
        )
        for stamp in range(START, START + 180000, 60000)
    ]

    def query(*args, **kwargs):
        return [
            row
            for row in rows
            if kwargs["start_ms"] <= row["open_time"] <= kwargs["end_ms"]
        ]

    adapter = BarPreparationAdapter(
        tmp_path / "chunks",
        coordinator=None,
        local_data=runtime.local_data,
        backtest_runtime=runtime,
        query=query,
    )
    binding = dict(
        exchange="binance",
        market_type="usdm",
        symbol="BTCUSDT",
        binding_symbol="BINANCE:BTCUSDT",
        interval="1m",
        range_mode="CUSTOM",
        fidelity_preference="FAST",
        start_time_ms=START,
        end_time_ms=START + 179999,
    )
    request = PreparationRequest(
        idempotency_key="legacy-alias-retry",
        consumer="STRATEGY",
        requirements=[
            Requirement(
                exchange="binance",
                market_type="usdm",
                symbol="BTCUSDT",
                start_ms=START,
                end_ms=START + 180000,
            )
        ],
        intent={
            "native_strategy": {
                "language": "pine",
                "source": '//@version=6\nstrategy("Legacy retry")\nplot(close)',
                "parameters": {},
                "libraries": {},
                "bindings": [binding],
                "dependency_requirements": [],
            }
        },
    )
    repo = PreparationRepository(tmp_path / "jobs.db")
    service = PreparationService(repo, adapter)
    resumed = None
    try:
        # Seed a real persisted failure using the previous raw-identity matcher.
        # The production publication, cached chunks and request are left intact.
        def previous_match(manifest, wanted):
            return (
                str(manifest.get("exchange") or "").lower() == wanted.exchange
                and str(manifest.get("market_type") or "").lower() == wanted.market_type
                and str(manifest.get("symbol") or "").upper() == wanted.symbol
            )

        with monkeypatch.context() as prior:
            prior.setattr(
                type(runtime.chart_context),
                "_manifest_matches",
                staticmethod(previous_match),
            )
            await service.start()
            job = await service.submit(request)
            failed = await terminal(service, job["id"], timeout=30)
            assert failed["state"] == "FAILED"
            assert failed["error"]["code"] == "DEPENDENCY_NOT_READY"
            await service.shutdown()
        before = {
            str(p.relative_to(runtime.local_data.root)): p.read_bytes()
            for p in runtime.local_data.root.rglob("*")
            if p.name in {"manifest.json", "bars.sqlite"}
        }
        assert before
        resumed = PreparationService(
            PreparationRepository(tmp_path / "jobs.db"), adapter
        )
        await resumed.start()
        await resumed.retry(job["id"])
        ready = await terminal(resumed, job["id"], timeout=30)
        assert ready["state"] == "READY", ready.get("error")
        assert ready["request"] == failed["request"]
        assert ready["fingerprint"] == failed["fingerprint"]
        assert ready["result"]["native_inputs"][0]["market_type"] == "usdm"
        key = ready["result"]["native_run"]["run_id"]
        for _ in range(1000):
            run = runtime.native.get(key)
            if run["state"] in {"COMPLETED", "FAILED"}:
                break
            await asyncio.sleep(0.02)
        assert run["state"] == "COMPLETED", run.get("error")
        assert before == {
            str(p.relative_to(runtime.local_data.root)): p.read_bytes()
            for p in runtime.local_data.root.rglob("*")
            if p.name in {"manifest.json", "bars.sqlite"}
        }
        repeated = await adapter.launch(request, ready["result"], job["id"])
        assert repeated["native_run"]["run_id"] == key
        assert len(runtime.native.list()) == 1
    finally:
        await service.shutdown()
        if resumed is not None:
            await resumed.shutdown()
        runtime.shutdown()
