from app.replay.training.review_account import legacy_account


def test_legacy_flat_global_balance_includes_all_markets_and_isolated_allocations():
    projection = {"domain": {"equity": "9999.56560194"}, "account": {"margin_mode": "CROSS"}, "tracks": [
        {"track_id": "track-1", "position": {"quantity": "0"}, "open_orders": [], "account": {"available_equity": "9999.84775598"}},
        {"track_id": "track-2", "position": {"position_mode": "HEDGE", "long": {"quantity": "0"}, "short": {"quantity": "0"}}, "open_orders": []},
    ]}
    assert legacy_account(projection)["available_equity"] == "9999.56560194"
    projection["account"] = {"margin_mode": "ISOLATED", "isolated_margin": {"track-1": "20.1", "track-2": "30.2"}}
    assert legacy_account(projection)["available_equity"] == "9949.26560194"
    projection["tracks"][1]["position"]["long"]["quantity"] = "1"
    projection["tracks"][1]["position"]["short"]["quantity"] = "2"
    result = legacy_account(projection)
    assert result["status"] == "LEGACY_PARTIAL"
    assert result["available_equity"] is None
    assert result["unrealized_pnl"] is None
    assert result["positions"] == [
        {"track_id": "track-2", "position_side": "LONG", "quantity": "1"},
        {"track_id": "track-2", "position_side": "SHORT", "quantity": "2"},
    ]
