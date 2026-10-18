from decimal import Decimal
from app.backtest.external_report import closed_trades


def fill(side, qty, price, fee=0, time=1000):
    return dict(side=side, qty=qty, price=price, fee=fee, event_time_ms=time)


def test_real_ltc_round_trip_and_open_position_not_counted():
    fills = [fill("BUY", 1, "63.436343"), fill("SELL", 1, "63.443655", time=2000)]
    assert closed_trades(fills[:1]) == []
    rows = closed_trades(fills)
    assert len(rows) == 1
    assert Decimal(rows[0]["profit"]) == Decimal("0.007312")


def test_pyramiding_partial_close_and_reversal_use_average_cost_and_split_fees():
    rows = closed_trades([
        fill("BUY", 2, 10, ".2"), fill("BUY", 2, 20, ".4"),
        fill("SELL", 1, 30, ".3"), fill("SELL", 5, 25, "1.25", time=2000),
        fill("BUY", 2, 20, ".4", time=3000),
    ])
    assert len(rows) == 2
    assert rows[0]["side"] == "long" and rows[1]["side"] == "short"
    assert Decimal(rows[0]["profit"]) == Decimal("43.35")
    assert Decimal(rows[1]["profit"]) == Decimal("9.1")
    assert Decimal(rows[0]["qty"]) == 4 and Decimal(rows[1]["qty"]) == 2
