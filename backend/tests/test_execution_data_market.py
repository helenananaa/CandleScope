"""ADR-BACKTEST-015 P5c4c: a research chart-book file runs in the Pine panel's CandleScope matching."""
from __future__ import annotations

import pytest

from app.backtest.errors import BacktestError
from app.backtest.external_market import check_execution_market, freeze_execution
from app.backtest.native_contracts import ExecutionData

EVENT = {"time_ms": 60_000, "role": "TRADES", "payload": {"source_event_kind": "AGG_TRADE", "source_sequence": 1}}


def test_a_chart_book_file_is_valid_execution_data():
    book = ExecutionData.model_validate({"symbol": "BTCUSDT", "exchange": "binance", "market_type": "usdm",
                                         "provenance": {"capture": "archive"}, "events": [EVENT]})
    assert (book.exchange, book.market_type) == ("binance", "usdm")
    plain = ExecutionData.model_validate({"symbol": "BTCUSDT", "events": [EVENT]})
    assert (plain.exchange, plain.market_type) == (None, None), "files without a market keep working"
    with pytest.raises(ValueError):
        ExecutionData.model_validate({"symbol": "BTCUSDT", "events": [EVENT], "venue": "binance"})


@pytest.mark.parametrize("file_market,run,accepted", [
    (("binance", "usdm"), ("binance", "futures"), True),   # the chart's USD-M is the book file's usdm
    (("binance", "usdm"), ("binance", "usdm"), True),
    (("Binance", "SPOT"), ("binance", "spot"), True),
    (("binance", "usdm"), ("local", "spot"), True),        # imported data: venue unknown, symbol checked only
    ((None, None), ("binance", "spot"), True),
    (("okx", "usdm"), ("binance", "futures"), False),
    (("binance", "spot"), ("binance", "futures"), False),
    ((None, "spot"), ("binance", "futures"), False),
])
def test_the_book_must_be_for_the_runs_market(file_market, run, accepted):
    data = {"symbol": "BTCUSDT", "exchange": file_market[0], "market_type": file_market[1], "events": [EVENT]}
    payload = {"exchange": run[0], "market_type": run[1]}
    if accepted:
        check_execution_market(data, payload)
    else:
        with pytest.raises(BacktestError) as refused:
            check_execution_market(data, payload)
        assert refused.value.code == "DATA_SNAPSHOT_MISMATCH"


def test_a_mismatched_book_is_refused_before_it_is_read():
    payload = {"execution_fidelity": "BOOK_ASSISTED", "exchange": "binance", "market_type": "spot",
               "context": {"symbol": "BINANCE:BTCUSDT"}, "interval": "1m",
               "execution_data": {"symbol": "BTCUSDT", "exchange": "binance", "market_type": "usdm", "events": [EVENT]}}
    with pytest.raises(BacktestError) as refused:
        freeze_execution(None, payload, bars=[])
    assert refused.value.code == "DATA_SNAPSHOT_MISMATCH"
