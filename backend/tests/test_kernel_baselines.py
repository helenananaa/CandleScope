"""ADR-BACKTEST-015 P6a: every bar-family fill clock x account model keeps its kernel digests."""
from __future__ import annotations

import pytest

from tests.kernel_baselines import ACCOUNT_MODELS, CLOCKS, _drive, _plain, assert_baseline, build, scripted_strategy


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
    """Stored checkpoints are plain JSON; a fresh kernel of the clock restores them unchanged."""
    kernel_type, settings, driver = CLOCKS[clock]
    try:
        kernel = kernel_type(account_model=account_model, **settings)
    except Exception:  # noqa: BLE001 - refusals are pinned by the baseline itself
        pytest.skip(f"{clock} refuses {account_model}")
    snapshots: list = []
    _drive(kernel, driver, scripted_strategy(shorts=account_model != "SPOT_CASH_V1"), snapshots)
    assert len(snapshots) == 1
    restored = kernel_type(account_model=account_model, **settings)
    restored.restore(snapshots[0])
    assert _plain(restored.snapshot()) == snapshots[0]
