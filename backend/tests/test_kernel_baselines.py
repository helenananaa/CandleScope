"""ADR-BACKTEST-015 P6: every bar-family fill clock x account model keeps its kernel digests.

P6a pinned them with the separate Pine kernels; since P6b/P6c the Host bar kernel runs every
clock itself (``SimulationKernel(bar_clock=...)``) and must reproduce them.
"""
from __future__ import annotations

import pytest

from tests.kernel_baselines import ACCOUNT_MODELS, CLOCKS, _drive, _plain, assert_baseline, build, make_kernel, scripted_strategy


@pytest.mark.parametrize("clock", sorted(CLOCKS))
def test_kernel_baseline(clock):
    current = build(clock)
    accepted = [name for name, entry in current["accounts"].items() if "refused" not in entry]
    assert accepted, f"{clock} accepts no account model"
    for name in accepted:
        assert current["accounts"][name]["summary"]["fills"] > 0, f"{name} never filled; the script exercises nothing"
    assert_baseline(current)


@pytest.mark.parametrize("clock", sorted(CLOCKS))
@pytest.mark.parametrize("account_model", ACCOUNT_MODELS)
def test_checkpoint_payload_restores_into_the_same_clock(clock, account_model):
    """Stored checkpoints are plain JSON; a fresh kernel on the same clock restores them unchanged."""
    driver = CLOCKS[clock][2]
    try:
        kernel = make_kernel(clock, account_model)
    except Exception:  # noqa: BLE001 - refusals are pinned by the baseline itself
        pytest.skip(f"{clock} refuses {account_model}")
    snapshots: list = []
    _drive(kernel, driver, scripted_strategy(shorts=account_model != "SPOT_CASH_V1"), snapshots)
    assert len(snapshots) == 1
    restored = make_kernel(clock, account_model)
    restored.restore(snapshots[0])
    assert _plain(restored.snapshot()) == snapshots[0]


def test_bar_clock_refuses_path_checkpoints_and_unknown_clocks():
    from app.market_dataset.snapshot import MarketDatasetError
    from app.simulation.kernel import SimulationKernel

    path = make_kernel("pine-chart-bar", "LINEAR_PERP_ONE_WAY_V1")
    snapshots: list = []
    _drive(path, "chart", scripted_strategy(shorts=True), snapshots)
    with pytest.raises(MarketDatasetError, match="own matcher"):
        SimulationKernel().restore(snapshots[0])
    with pytest.raises(MarketDatasetError, match="own clock"):
        SimulationKernel(bar_clock="PINE_PATH").restore(snapshots[0])
    with pytest.raises(MarketDatasetError, match="unknown bar clock"):
        SimulationKernel(bar_clock="TICK")
    with pytest.raises(MarketDatasetError, match="no OHLC path"):
        SimulationKernel().walk_bar(None, lambda _: None)


def test_the_pine_bar_kernels_stay_folded_into_the_host_kernel():
    """ADR-BACKTEST-015 P6c: merging an older branch must not bring the separate Pine bar kernels back."""
    import importlib.util

    for name in ("pine_bar_kernel", "pine_chart_kernel", "pine_v2_bar_kernel"):
        assert importlib.util.find_spec(f"app.simulation.{name}") is None, f"app/simulation/{name}.py is back"
