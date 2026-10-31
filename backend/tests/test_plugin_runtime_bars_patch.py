"""batch-execution.bars-patch/1 from host rows through the supervisor to a real sidecar."""

from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest
from candlescope_plugin_sdk import FEATURE_BATCH_BARS_PATCH_V1, KNOWN_FEATURES_V1, ProtocolError

from app.data_engine.data_manager.models import BarData
from app.indicator.runtime_service import IndicatorRuntimeRequest, _sdk_bars, _to_sdk_bar
from app.plugin_runtime.registry import RuntimeProcessSpec
from app.plugin_runtime.supervisor import RuntimeSupervisor


FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures" / "plugin_runtime"
SOURCE = (
    '//@version=6\nindicator("live")\nvarip int ticks = 0\nticks += 1\n'
    'plot(close, color=close > open ? color.green : color.red)\nplot(ticks)\n'
    'plot(ta.sma(close, 5), offset=2)\nplotshape(close > open, style=shape.circle)\n'
)


def _pine(journal: Path, *, bars_patches: bool) -> RuntimeSupervisor:
    return RuntimeSupervisor(
        RuntimeProcessSpec(
            runtime_id="candlescope.pine-compat",
            expected_package="candlescope-plugin-pine-compat",
            expected_version="0.4.0",
            executable=Path(sys.executable).resolve(),
            arguments=("-u", str(FIXTURE_DIRECTORY / "run_pine_runtime.py"), str(journal)),
            working_directory=FIXTURE_DIRECTORY,
            startup_timeout_seconds=60.0,
            request_timeout_seconds=60.0,
            shutdown_timeout_seconds=5.0,
            # The walk restarts the sidecar on purpose.
            max_restart_attempts=10,
        ),
        host_name="CandleScope",
        host_version="0.3.0",
        host_features=tuple(
            feature for feature in KNOWN_FEATURES_V1
            if bars_patches or feature != FEATURE_BATCH_BARS_PATCH_V1
        ),
    )


def _row(index: int, close: float, closed: bool = True) -> BarData:
    return BarData(time=1_700_000_000 + index * 60, open=100.0, high=max(close, 100.0) + 1,
                   low=min(close, 100.0) - 1, close=close, volume=1.0, is_closed=closed)


def _record_bars(supervisor: RuntimeSupervisor) -> list[tuple[dict | None, int]]:
    """(barsPatch, number of bars) of every executeBatch the supervisor sends."""
    sent: list[tuple[dict | None, int]] = []
    original = supervisor._request_locked

    async def recording(method, params, *, timeout):
        if method == "executeBatch":
            sent.append((params.get("barsPatch"), len(params["bars"])))
        return await original(method, params, timeout=timeout)

    supervisor._request_locked = recording
    return sent


def test_stream_bars_equal_converting_every_row() -> None:
    rng = random.Random("stream-bars")
    closes = [100 + rng.uniform(-1, 1) for _ in range(300)]
    window, forming, previous = 0, 100.0, None
    for step in range(80):
        action = rng.choice(["tick", "same", "confirm", "slide", "correct"])
        if action == "tick":
            forming += 0.01
        elif action == "confirm":
            closes.append(forming)
            forming = closes[-1] + 0.5
        elif action == "slide":
            window += rng.randint(1, 5)
        elif action == "correct":
            closes[rng.randrange(window, len(closes))] += 0.25
        # Fresh row objects every time, as each query returns them.
        rows = [_row(i, close) for i, close in enumerate(closes)][window:] + [_row(len(closes), forming, closed=False)]
        if step % 5 == 2:
            rows = [{"time": row.time, "open": row.open, "high": row.high, "low": row.low, "close": row.close,
                     "volume": row.volume, "is_closed": row.is_closed} for row in rows]
        bars = _sdk_bars("stream-bars", tuple(rows))
        assert bars == tuple(_to_sdk_bar(row) for row in rows)
        if previous is not None and action in {"tick", "same"}:
            # Rows with unchanged values map to the very Bars converted before.
            assert all(a is b for a, b in zip(bars[:-1], previous[:-1]))
            assert (bars[-1] is previous[-1]) == (action == "same")
        previous = bars

    # Rows the fast path cannot read are converted one by one, as before.
    mixed = (_row(0, 100), {"time": 1_700_000_060, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 3})
    assert _sdk_bars("stream-bars", mixed) == tuple(_to_sdk_bar(row) for row in mixed)
    camel = ({"time": 1_700_000_000, "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 3, "isClosed": False},)
    assert _sdk_bars("stream-bars", camel)[0].is_closed is False
    with pytest.raises(ProtocolError):
        _sdk_bars("stream-bars", (_row(0, float("nan")),))


@pytest.mark.anyio
async def test_patched_requests_give_callers_the_full_request_result(tmp_path) -> None:
    pytest.importorskip("pine_compat")
    rng = random.Random("supervisor-bars-patch")
    patched = _pine(tmp_path / "patched.sqlite3", bars_patches=True)
    full = _pine(tmp_path / "full.sqlite3", bars_patches=False)
    sent, sent_full = _record_bars(patched), _record_bars(full)
    closes = [100 + (i % 7) + rng.uniform(-0.5, 0.5) for i in range(400)]
    window, forming = 0, 100.0
    events = []

    def request(stream: str = "live"):
        # New row objects for every request, as each tick queries them again.
        rows = [_row(i, close) for i, close in enumerate(closes)][window:]
        if forming is not None:
            rows.append(_row(len(closes), forming, closed=False))
        return IndicatorRuntimeRequest(
            language="pine", source=SOURCE, exchange="binance", market_type="spot", symbol="BTCUSDT",
            interval="1m", bars=tuple(rows), options={"pineSessionId": stream}, transport="websocket.snapshot",
        ).to_sdk_request()

    try:
        # Rare events at fixed steps, so every seed covers them.
        schedule = {0: "seed", 7: "evict", 12: "restart", 18: "forget", 23: "catchup", 27: "correct",
                    31: "evict", 35: "restart", 38: "forget"}
        for step in range(44):
            action = schedule.get(step) or rng.choices(
                ["tick", "confirm", "catchup", "slide", "correct"], weights=[12, 4, 2, 3, 2])[0]
            if action == "tick":
                forming = (forming if forming is not None else closes[-1]) + rng.uniform(-0.6, 0.6)
            elif action == "confirm" and forming is not None:
                closes.append(forming)
                forming = None
            elif action == "catchup":
                if forming is not None:
                    closes.append(forming)
                closes.extend(closes[-1] + rng.uniform(-1, 1) for _ in range(rng.choice([3, 64])))
                forming = closes[-1] + 0.1
            elif action == "slide":
                window += rng.randint(1, 8)
            elif action == "correct":
                closes[rng.randrange(window, len(closes))] += 0.37
            elif action == "restart":
                # A restarted sidecar keeps its journal; the host drops its bases.
                await patched.stop()
                await full.stop()
            elif action == "evict":
                for other in range(9):
                    await patched.execute_batch(request(f"other-{other}"))
                    await full.execute_batch(request(f"other-{other}"))
            elif action == "forget":
                # The runtime no longer holds the host's base: it answers
                # BARS_PATCH_BASE_UNKNOWN and the host resends every bar.
                generation, _revision, bars = patched._bars["live"]
                patched._bars["live"] = (generation, "forgotten", bars)
            events.append(action)
            sdk_request = request()
            mark = len(sent)
            expected = await full.execute_batch(sdk_request)
            actual = await patched.execute_batch(sdk_request)
            assert expected.ok, expected.diagnostics
            assert actual == expected, events
            assert actual.bars_revision is None and actual.output_revision is None
            this = sent[mark:]
            if action == "tick":
                assert [count for _patch, count in this] == [1] and this[0][0]["base"], (this, events)
            if action == "forget":
                assert [patch["base"] for patch, _count in this] == ["forgotten", None], (this, events)
                assert this[1][1] == len(sdk_request.bars)
    finally:
        await patched.stop()
        await full.stop()

    assert all(patch is None for patch, _count in sent_full)
    assert patched._remote_error_count == 0
    assert sum(1 for patch, _count in sent if patch is not None and patch["base"]) >= 25, (sent, events)
