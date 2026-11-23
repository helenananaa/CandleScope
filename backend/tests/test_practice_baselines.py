"""ADR-BACKTEST-015 P6e: practice accounts keep their behaviour while their account model becomes the shared one."""
from __future__ import annotations

from tests.practice_baselines import VARIANTS, assert_baseline, build


def test_practice_account_baseline(tmp_path):
    current = build(tmp_path)
    for name in VARIANTS:
        assert current["variants"][name]["summary"]["fills"] > 0, f"{name} never filled; the script exercises nothing"
    assert_baseline(current)
