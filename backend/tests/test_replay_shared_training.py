import pytest
from tests.fixtures.replay.shared_market_fakes import install_shared_market
from tests.test_replay_interval_advance import (
    test_waiting_order_skips_safe_prefix_and_stops_at_first_fill as run_case,
)


@pytest.mark.anyio
@pytest.mark.parametrize("side,margin", [("LONG", "CROSS"), ("SHORT", "ISOLATED")])
async def test_shared_financial_reference_and_recovery(
    tmp_path, monkeypatch, side, margin
):
    install_shared_market(monkeypatch, tmp_path / "market")
    await run_case(
        tmp_path,
        monkeypatch,
        False,
        0,
        True,
        side,
        margin,
        True,
        indexed=True,
        shared=True,
        previous_checkpoint=True,
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "event", ["order", "funding", "liquidation", "hidden", "review"]
)
async def test_shared_exact_event_boundaries(tmp_path, monkeypatch, event):
    install_shared_market(monkeypatch, tmp_path / "market")
    kwargs = {}
    if event == "liquidation":
        kwargs = {
            "liquidation": True,
            "initial_equity": "100",
            "holding_quantity": "2",
            "mark_prices": ["100"] * 180 + ["40"] * 81,
        }
    if event == "hidden":
        kwargs["time_disclosure_policy"] = "HIDE_ALL"
    if event == "review":
        kwargs["review_fork"] = True
    await run_case(
        tmp_path,
        monkeypatch,
        event == "order",
        180 if event == "funding" else 0,
        True,
        "LONG",
        "CROSS",
        True,
        indexed=True,
        shared=True,
        touch_offset=180,
        **kwargs,
    )


@pytest.mark.anyio
async def test_shared_transaction_failure_restores_source_anchor(tmp_path, monkeypatch):
    from tests.test_replay_indexed_interval import (
        test_indexed_jump_failure_rolls_back_all_durable_state,
    )

    install_shared_market(monkeypatch, tmp_path / "market")
    await test_indexed_jump_failure_rolls_back_all_durable_state(
        tmp_path, monkeypatch, shared=True
    )


@pytest.mark.anyio
async def test_shared_flat_account(tmp_path, monkeypatch):
    install_shared_market(monkeypatch, tmp_path / "market")
    await run_case(
        tmp_path,
        monkeypatch,
        False,
        0,
        False,
        varying_mark=True,
        indexed=True,
        shared=True,
    )
