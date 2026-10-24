from decimal import Decimal
import pytest
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


@pytest.mark.parametrize("multiplier", [Decimal(50), Decimal(".01")])
def test_contract_round_trip_preserves_prices_and_converts_pnl_and_return_basis(multiplier):
    rows = closed_trades([fill("BUY", 2, 10, ".2"), fill("SELL", 2, 20, ".4")],
                         contract_multiplier=multiplier)
    profit = 20 * multiplier - Decimal(".6")
    assert Decimal(rows[0]["profit"]) == profit
    assert Decimal(rows[0]["entryPrice"]) == 10
    assert Decimal(rows[0]["exitPrice"]) == 20
    assert Decimal(rows[0]["return_percent"]) == profit / (20 * multiplier) * 100


def test_effective_fill_multiplier_survives_csv_and_drives_both_trade_reports():
    import csv
    import io
    from app.backtest.reports import _fills_csv, build_round_trip_trades

    fills = [{**fill("BUY", 2, 10, ".2"), "contract_multiplier": "50", "sequence": 1},
             {**fill("SELL", 2, 20, ".4"), "contract_multiplier": "25", "sequence": 2}]
    exported = list(csv.DictReader(io.StringIO(_fills_csv(fills))))
    assert [row["contract_multiplier"] for row in exported] == ["50", "25"]
    profit = Decimal("499.4")
    # The close uses its effective rule; the percentage basis keeps the entry's.
    episode = closed_trades(fills, contract_multiplier=Decimal(999))[0]
    assert Decimal(episode["profit"]) == profit
    assert Decimal(episode["return_percent"]) == profit / 1000 * 100
    assert Decimal(build_round_trip_trades(exported)[0]["net_pnl"]) == profit


def test_execution_turnover_and_slippage_use_contract_notional():
    from app.backtest.metrics_v2 import _execution_metrics

    data = {"fills": [{**fill("BUY", 2, 11), "contract_multiplier": "50", "sequence": 1}]}
    curve = [{"equity": "10000"}]
    result = _execution_metrics(data, {}, curve, {"fill_source_prices": {"1": "10"}})
    assert Decimal(result["turnover"]["value"]) == Decimal(".11")
    assert Decimal(result["slippage"]["value"]) == 100
