"""Small global account summaries for immutable review frames."""

from decimal import Decimal

from app.replay.broker.models import decimal_to_string
from .persistence import portfolio as portfolio_ops
from .errors import TrainingRunError


def capture_account(connection, run_id):
    initial = connection.execute("SELECT initial_equity FROM replay_training_run WHERE run_id=?", (run_id,)).fetchone()[0]
    tracks = [portfolio_ops.market_track_from_row(row) for row in connection.execute(
        "SELECT * FROM replay_training_market_track WHERE run_id=? ORDER BY stable_ordinal", (run_id,),
    )]
    try:
        portfolio = portfolio_ops.contract_portfolio_projection(
            connection, run_id=run_id, initial_equity=initial, tracks=tracks, live=True,
        )
    except TrainingRunError as exc:
        if exc.code != "TRAINING_RUN_STORAGE_DEGRADED":
            raise
        # A failed valuation must remain explicit, but must not prevent saving
        # and closing a degraded run or turn an old broker balance into truth.
        return {"status": "UNAVAILABLE", "equity": None, "available_equity": None,
                "unrealized_pnl": None, "margin_used": None, "reserved_margin": None, "positions": None}
    return {"status": "EXACT_SNAPSHOT", **{key: portfolio[key] for key in (
        "equity", "available_equity", "unrealized_pnl", "margin_used", "reserved_margin",
    )}, "positions": [{"track_id": item["track_id"], "position_side": item.get("position_side", "NET"),
                        "quantity": item["position"]["quantity"]} for item in portfolio["positions"]]}


def legacy_account(projection):
    """Never substitute a single adapter's buying power for the global wallet.

    Older flat, order-free frames have an exact recoverable free balance.
    Held legacy frames lack the global risk valuation; expose that gap instead
    of inventing margin/PnL from independent broker marks.
    """
    positions = []
    for track in projection["tracks"]:
        position = track["position"]
        legs = [("NET", position)] if position.get("position_mode") != "HEDGE" else [
            ("LONG", position["long"]), ("SHORT", position["short"]),
        ]
        for side, leg in legs:
            if Decimal(leg.get("quantity", "0")) != 0:
                positions.append({"track_id": track["track_id"], "position_side": side, "quantity": leg["quantity"]})
    orders = [order for track in projection["tracks"] for order in track["open_orders"]]
    equity = str(projection["domain"]["equity"])
    complete = not positions and not orders
    allocated = sum((Decimal(v) for v in projection["account"].get("isolated_margin", {}).values()), Decimal(0))
    available = Decimal(equity) - (allocated if projection["account"].get("margin_mode") == "ISOLATED" else 0)
    return {"status": "LEGACY_FLAT" if complete else "LEGACY_PARTIAL", "equity": equity,
            "available_equity": decimal_to_string(available, field_name="available_equity") if complete else None,
            "unrealized_pnl": "0" if complete else None, "positions": positions}
