"""ADR-BACKTEST-015 P6: every bar-family fill clock x account model keeps its kernel digests.

P6a pinned them with the separate Pine kernels; since P6b the Host bar kernel runs every clock
itself, and must reproduce them under the old class names and as ``SimulationKernel(bar_clock=...)``.
"""
from __future__ import annotations

import pytest

from tests.kernel_baselines import (
    ACCOUNT_MODELS, CLOCKS, HOST_CLOCK, _drive, _plain, assert_baseline, build, make_kernel, scripted_strategy,
)


@pytest.mark.parametrize("clock", sorted(CLOCKS))
def test_kernel_baseline(clock):
    current = build(clock)
    accepted = [name for name, entry in current["accounts"].items() if "refused" not in entry]
    assert accepted, f"{clock} accepts no account model"
    for name in accepted:
        assert current["accounts"][name]["summary"]["fills"] > 0, f"{name} never filled; the script exercises nothing"
    assert_baseline(current)


@pytest.mark.parametrize("clock", sorted(clock for clock, (kernel_type, _, _) in CLOCKS.items() if kernel_type in HOST_CLOCK))
def test_host_bar_kernel_reproduces_each_pine_clock(clock):
    """ADR-BACKTEST-015 P6b: SimulationKernel(bar_clock=...) gives the old kernels' digests, refusals and checkpoints."""
    current = build(clock, host=True)
    for entry in current["accounts"].values():
        if "summary" in entry:
            entry["summary"]["kernel"] = CLOCKS[clock][0].__name__
    assert_baseline(current)


@pytest.mark.parametrize("host", [False, True], ids=["class", "host"])
@pytest.mark.parametrize("clock", sorted(CLOCKS))
@pytest.mark.parametrize("account_model", ACCOUNT_MODELS)
def test_checkpoint_payload_restores_into_the_same_clock(clock, account_model, host):
    """Stored checkpoints are plain JSON; a fresh kernel of the clock restores them unchanged, by either name."""
    driver = CLOCKS[clock][2]
    try:
        kernel = make_kernel(clock, account_model)
    except Exception:  # noqa: BLE001 - refusals are pinned by the baseline itself
        pytest.skip(f"{clock} refuses {account_model}")
    snapshots: list = []
    _drive(kernel, driver, scripted_strategy(shorts=account_model != "SPOT_CASH_V1"), snapshots)
    assert len(snapshots) == 1
    restored = make_kernel(clock, account_model, host=host)
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
