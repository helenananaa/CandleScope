"""render.output-patch/1 between the host supervisor and real sidecars."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest
from candlescope_plugin_sdk import Bar, ExecuteBatchRequest, ExecuteBatchResult, MarketContext

from app.plugin_runtime.registry import RuntimeProcessSpec
from app.plugin_runtime.supervisor import RuntimeSupervisor


FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "plugin_runtime"
SOURCE = (
    '//@version=6\nindicator("live")\nvarip int ticks = 0\nticks += 1\n'
    'plot(close, color=close > open ? color.green : color.red)\nplot(ticks)\n'
    'plotshape(close > open, style=shape.circle)\n'
)
CONTEXT = MarketContext(exchange="binance", market_type="spot", symbol="BTCUSDT", interval="1m")


def _supervisor(arguments: tuple[str, ...], runtime_id: str, package: str, version: str) -> RuntimeSupervisor:
    return RuntimeSupervisor(
        RuntimeProcessSpec(
            runtime_id=runtime_id,
            expected_package=package,
            expected_version=version,
            executable=Path(sys.executable).resolve(),
            arguments=("-u", *arguments),
            working_directory=FIXTURE_DIRECTORY,
            startup_timeout_seconds=60.0,
            request_timeout_seconds=60.0,
            shutdown_timeout_seconds=5.0,
        ),
        host_name="CandleScope",
        host_version="0.3.0",
    )


def _pine(journal: Path) -> RuntimeSupervisor:
    return _supervisor((str(FIXTURE_DIRECTORY / "run_pine_runtime.py"), str(journal)),
                       "candlescope.pine-compat", "candlescope-plugin-pine-compat", "0.4.0")


def _bar(index: int, close: float, closed: bool = True) -> Bar:
    return Bar(time=1_700_000_000 + index * 60, open=100, high=max(close, 100) + 1,
               low=min(close, 100) - 1, close=close, volume=1, is_closed=closed)


@pytest.mark.anyio
async def test_patched_stream_gives_callers_the_full_snapshot_result(tmp_path, monkeypatch) -> None:
    pytest.importorskip("pine_compat")
    applied = []
    patched_result = ExecuteBatchResult.patched

    def counting(self, base):
        applied.append(self.output_revision)
        return patched_result(self, base)

    monkeypatch.setattr(ExecuteBatchResult, "patched", counting)
    patched, full = _pine(tmp_path / "patched.sqlite3"), _pine(tmp_path / "full.sqlite3")
    history = [_bar(i, 100 + (i % 7)) for i in range(400)]
    try:
        for step in range(16):
            if step == 9:
                # A restarted sidecar keeps its journal; the stale base is dropped.
                await patched.stop()
                await full.stop()
            if step % 5 == 4:
                history.append(_bar(len(history), 101))
            bars = (*history, _bar(len(history), 99 + step * 0.25, closed=False))
            request = ExecuteBatchRequest(source=SOURCE, context=CONTEXT, bars=bars,
                                          options={"pineSessionId": "live"})
            expected = await full.execute_batch(request)
            actual = await patched.execute_batch(replace(request, output_stream="live"))
            assert expected.ok, expected.diagnostics
            assert actual == expected
        assert len(applied) >= 12
    finally:
        await patched.stop()
        await full.stop()


@pytest.mark.anyio
async def test_stream_is_not_sent_to_a_runtime_without_the_feature() -> None:
    hello = _supervisor((str(FIXTURE_DIRECTORY / "run_hello_runtime.py"),),
                        "hello-runtime", "candlescope-plugin-sdk", "0.2.0")
    request = ExecuteBatchRequest(source="plot(close)", context=CONTEXT, bars=(_bar(0, 101), _bar(1, 102)))
    try:
        expected = await hello.execute_batch(request)
        actual = await hello.execute_batch(replace(request, output_stream="live"))
        assert actual == expected and actual.output is not None
    finally:
        await hello.stop()
