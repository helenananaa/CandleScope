from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.data_engine.ingestion.models import DataSource, RawMessage, StreamDescriptor, StreamType
from app.data_engine.storage import klines_repo, kline_sources
from app.exchanges.ccxt_ext.fork_kline import normalize_fork_kline
from tests.test_ccxt_fork_kline import DESCRIPTOR, FRAME, MARKET, ROW, fork_exchange


@pytest.fixture
def database(tmp_path, monkeypatch):
    path = tmp_path / "klines.sqlite"
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", path)
    klines_repo.init_klines_storage()
    return path


def event(*, closed=True, quote="1010", timestamp=1772323200001):
    frame = copy.deepcopy(FRAME)
    frame["E"] = timestamp
    frame["k"].update(x=closed, q=quote)
    payload = fork_exchange().parse_candlescope_ws_kline(frame)
    return normalize_fork_kline(
        RawMessage(
            payload, DataSource.WEBSOCKET, DESCRIPTOR.stream_type, timestamp + 100
        ),
        DESCRIPTOR,
    )


def record(value, watermark=None):
    return kline_sources.record(value, DESCRIPTOR, rest_watermark=watermark)


def test_exact_source_and_revision_survive_a_separate_process(database):
    first = record(event())
    revised = record(event(quote="1009", timestamp=1772323200002))
    assert first["ref"]["revision"] == 1
    assert revised["ref"]["revision"] == 2
    assert record(event(quote="1009", timestamp=1772323200002))["ref"] == revised["ref"]
    code = """import json,sys
from pathlib import Path
from app.data_engine.storage import klines_repo,kline_sources
from app.data_engine.ingestion.models import StreamDescriptor,StreamType
klines_repo.KLINES_DB_PATH=Path(sys.argv[1])
print(json.dumps(kline_sources.latest(StreamDescriptor('BTCUSDT',StreamType.KLINE,interval='1M',market_type='futures'),1769904000000)))
"""
    value = json.loads(
        subprocess.check_output(
            [sys.executable, "-c", code, str(database)],
            text=True,
            cwd=Path(__file__).resolve().parents[1],
        )
    )
    assert value["revision"] == 2
    assert value["envelope"]["open"] == ROW[1]
    assert json.loads(value["envelope"]["raw"])["k"]["q"] == "1009"
    assert len(kline_sources.observations(DESCRIPTOR, ROW[0])) == 2


def test_stale_forming_and_equal_timestamp_conflicts_do_not_change_closed_head(
    database,
):
    record(event())
    assert record(event(closed=False, timestamp=1772323200002))["status"] == "stale"
    assert record(event(quote="1008", timestamp=1772323200000))["status"] == "stale"
    assert record(event(quote="1008"))["status"] == "reconcile"
    assert kline_sources.latest(DESCRIPTOR, ROW[0])["revision"] == 1
    assert len(kline_sources.observations(DESCRIPTOR, ROW[0])) == 4


def test_rest_inflight_response_cannot_overwrite_newer_ws_and_cross_source_conflict_requires_rest(
    database,
):
    watermark = kline_sources.rest_watermark()
    record(event())
    raw = list(ROW)
    raw[7] = "1008"
    payload = fork_exchange().parse_candlescope_kline(raw, MARKET, "1M")
    rest = normalize_fork_kline(
        RawMessage(payload, DataSource.HTTP, DESCRIPTOR.stream_type, 1772323200100),
        DESCRIPTOR,
    )
    assert record(rest, watermark)["status"] == "stale"
    accepted = record(rest, kline_sources.rest_watermark())
    assert accepted["ref"]["revision"] == 2
    assert record(event(quote="1011", timestamp=1772323200200))["status"] == "reconcile"
    assert kline_sources.latest(DESCRIPTOR, ROW[0])["envelope"]["quoteVolume"] == "1008"


# RC 35 evidence: Binance USD-M BTCUSDT 1m, 2026-11-24 11:23 UTC. The WS x=true
# close is Binance's final candle; the REST read 2.2 s (exchange clock) after
# the close still served the snapshot from ~0.5 s before it.
RC35 = StreamDescriptor("BTCUSDT", StreamType.KLINE, interval="1m", market_type="futures")
RC35_OPEN = 1795519380000
RC35_CLOSE = RC35_OPEN + 59_999


def rc35_row(close, volume, quote, trades, taker_base, taker_quote):
    return [RC35_OPEN, "59629.50", "59637.20", "59602.10", close, volume, RC35_CLOSE,
            quote, trades, taker_base, taker_quote, "0"]


RC35_WS_CLOSE = rc35_row("59631.10", "60.767", "3622772.97970", 1987, "31.483", "1876886.74380")
RC35_REST_LAGGING = rc35_row("59633.20", "59.917", "3572086.08720", 1960, "31.385", "1871042.81230")


def rc35_envelope(row):
    names = ("timestamp", "open", "high", "low", "close", "volume", "closeTime",
             "quoteVolume", "trades", "takerBuyBaseVolume", "takerBuyQuoteVolume")
    return {"schema": "candlescope.binance.usdm.kline.v1", "exchange": "binance",
            "marketType": "swap.linear", "marketId": "BTCUSDT", "symbol": "BTC/USDT:USDT",
            "timeframe": "1m", "volumeUnit": "base", "quoteVolumeUnit": "quote",
            **dict(zip(names, row[:11]))}


def rc35_ws(row, *, closed=True, event_time=RC35_CLOSE + 97):
    kline = dict(zip(("t", "o", "h", "l", "c", "v", "T", "q", "n", "V", "Q"),
                     (row[0], *row[1:6], row[6], row[7], row[8], row[9], row[10])))
    frame = {"e": "kline", "E": event_time, "s": "BTCUSDT",
             "k": {**kline, "s": "BTCUSDT", "i": "1m", "x": closed, "B": "0"}}
    payload = dict(rc35_envelope(row), closed=closed, closeEvidence="ws_x",
                   eventTime=event_time, raw=json.dumps(frame))
    return normalize_fork_kline(
        RawMessage(payload, DataSource.WEBSOCKET, StreamType.KLINE, event_time - 400), RC35)


def rc35_rest(row, *, server_time):
    payload = dict(rc35_envelope(row), closed=None, closeEvidence="rest_close_time",
                   _source_rest_server_time_ms=server_time, raw=json.dumps(row))
    return normalize_fork_kline(
        RawMessage(payload, DataSource.HTTP, StreamType.KLINE, server_time + 900), RC35)


def rc35_record(value, watermark=None):
    return kline_sources.record(value, RC35, rest_watermark=watermark)


@pytest.mark.parametrize("ws_closed", [True, False])
def test_lagging_rest_snapshot_cannot_replace_a_newer_ws_candle(database, ws_closed):
    # A forming WS update just before the close is newer than the lagging REST too.
    event_time = RC35_CLOSE + 97 if ws_closed else RC35_CLOSE - 300
    ws = rc35_record(rc35_ws(RC35_WS_CLOSE, closed=ws_closed, event_time=event_time))
    assert ws["status"] == "selected"
    # Requested after the WS observation was recorded, as in RC 35.
    watermark = kline_sources.rest_watermark()
    lagging = rc35_rest(RC35_REST_LAGGING, server_time=RC35_CLOSE + 2_242)
    assert lagging.data["is_closed"] is True
    assert rc35_record(lagging, watermark)["status"] == "stale"
    head = kline_sources.latest(RC35, RC35_OPEN)
    assert (head["revision"], head["source"], head["envelope"]["trades"]) == (1, "websocket", 1987)
    # Once REST has caught up it confirms the WS close without a revision (and
    # only closes a forming head).
    caught_up = rc35_record(rc35_rest(RC35_WS_CLOSE, server_time=RC35_CLOSE + 5_000),
                            kline_sources.rest_watermark())
    assert caught_up["status"] == "selected"
    assert caught_up["ref"]["revision"] == (1 if ws_closed else 2)


def test_rest_ahead_of_ws_or_after_close_lag_still_revises_the_candle(database):
    rc35_record(rc35_ws(RC35_WS_CLOSE))
    ahead = rc35_row("59631.10", "60.800", "3624740.00000", 1990, "31.483", "1876886.74380")
    revised = rc35_record(rc35_rest(ahead, server_time=RC35_CLOSE + 2_242),
                          kline_sources.rest_watermark())
    assert revised["status"] == "selected" and revised["ref"]["revision"] == 2
    # Past the REST cache lag a lower snapshot is an exchange correction again.
    late = rc35_rest(RC35_REST_LAGGING, server_time=RC35_CLOSE + kline_sources.REST_CLOSE_LAG_MS + 1)
    corrected = rc35_record(late, kline_sources.rest_watermark())
    assert corrected["status"] == "selected" and corrected["ref"]["revision"] == 3
    assert kline_sources.latest(RC35, RC35_OPEN)["envelope"]["trades"] == 1960


def test_pending_delivery_ack_is_revision_scoped(database):
    first = record(event())
    record(event(quote="1009", timestamp=1772323200002))
    kline_sources.acknowledge(first["ref"])
    pending = kline_sources.pending(DESCRIPTOR)
    assert len(pending) == 1
    assert pending[0].payload["_source_receipt"]["ref"]["revision"] == 2
    kline_sources.acknowledge(pending[0].payload["_source_receipt"]["ref"])
    assert not kline_sources.pending(DESCRIPTOR)


def test_revision_identity_retains_more_than_28_decimal_digits(database):
    first = record(event(quote="1010.0000000000000000000000000001"))
    second = record(
        event(quote="1010.0000000000000000000000000002", timestamp=1772323200002)
    )
    assert second["ref"]["revision"] == first["ref"]["revision"] + 1


def test_batch_failure_rolls_back_source_head_and_observations(database, monkeypatch):
    original = kline_sources.record

    def fail_second(value, *args, **kwargs):
        if value.data["quote_volume"] == 1009:
            raise OSError("injected disk failure")
        return original(value, *args, **kwargs)

    monkeypatch.setattr(kline_sources, "record", fail_second)
    with pytest.raises(OSError):
        kline_sources.record_batch([event(), event(quote="1009")], DESCRIPTOR, None)
    assert not kline_sources.observations(DESCRIPTOR, ROW[0])
    assert kline_sources.latest(DESCRIPTOR, ROW[0]) is None


def fetched_rest_bar():
    from app.data_engine.backfill.fetcher import HistoricalFetcher
    from app.data_engine.backfill.models import BackfillTask

    payload = fork_exchange().parse_candlescope_kline(ROW, MARKET, "1M")
    raw = RawMessage(payload, DataSource.HTTP_BACKFILL, DESCRIPTOR.stream_type, 1772323200100)
    normalized = normalize_fork_kline(raw, DESCRIPTOR)
    receipt = record(normalized, kline_sources.rest_watermark())
    raw.payload = dict(payload, _source_receipt=receipt)
    task = BackfillTask(symbol=DESCRIPTOR.symbol, interval="1M", start_ms=ROW[0],
                        end_ms=ROW[0], estimated_bars=1, market_type="futures")
    return HistoricalFetcher._event_to_bar(normalize_fork_kline(raw, DESCRIPTOR), task)


def write_history(bar, **kwargs):
    return klines_repo.upsert_klines(DESCRIPTOR.symbol, "1M", [bar.to_storage_dict()],
                                    source="backfill", market_type="futures", **kwargs)


def test_durable_rest_history_is_not_replayed_as_realtime_after_restart(database):
    bar = fetched_rest_bar()
    assert len(kline_sources.pending(DESCRIPTOR)) == 1
    assert write_history(bar) == 1
    # pending opens another connection, as the next pipeline startup does.
    assert not kline_sources.pending(DESCRIPTOR)
    assert kline_sources.latest(DESCRIPTOR, ROW[0])["delivered_revision"] == 1


def test_history_receipt_and_projection_roll_back_together(database):
    bar = fetched_rest_bar()
    with klines_repo._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        assert write_history(bar, _connection=conn) == 1
        assert conn.execute("SELECT delivered_revision FROM kline_source_heads").fetchone()[0] == 1
        conn.rollback()
    assert len(kline_sources.pending(DESCRIPTOR)) == 1
    with klines_repo._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM klines").fetchone()[0] == 0


def test_superseded_rest_history_cannot_acknowledge_new_source_head(database):
    bar = fetched_rest_bar()
    raw = list(ROW)
    raw[7] = "1008"
    payload = fork_exchange().parse_candlescope_kline(raw, MARKET, "1M")
    newer = normalize_fork_kline(RawMessage(payload, DataSource.HTTP_BACKFILL,
                                          DESCRIPTOR.stream_type, 1772323200200), DESCRIPTOR)
    record(newer, kline_sources.rest_watermark())
    assert write_history(bar) == 0
    assert kline_sources.latest(DESCRIPTOR, ROW[0])["delivered_revision"] == 0
    assert kline_sources.pending(DESCRIPTOR)[0].payload["_source_receipt"]["ref"]["revision"] == 2


def test_realtime_projection_still_waits_for_market_delivery_ack(database):
    bar = fetched_rest_bar()
    assert klines_repo.upsert_klines(DESCRIPTOR.symbol, "1M", [bar.to_storage_dict()],
                                   source="data_manager_exchange_closed", market_type="futures") == 1
    assert len(kline_sources.pending(DESCRIPTOR)) == 1


def test_backfill_cannot_acknowledge_a_websocket_head(database):
    from app.data_engine.backfill.fetcher import HistoricalFetcher
    from app.data_engine.backfill.models import BackfillTask

    value = event()
    value.data["source_ref"] = record(value)["ref"]
    task = BackfillTask(symbol=DESCRIPTOR.symbol, interval="1M", start_ms=ROW[0],
                        end_ms=ROW[0], market_type="futures")
    bar = HistoricalFetcher._event_to_bar(value, task)
    assert write_history(bar) == 1
    assert len(kline_sources.pending(DESCRIPTOR)) == 1


def test_failed_history_write_keeps_receipt_pending(database):
    import sqlite3

    bar = fetched_rest_bar()
    with klines_repo._connect() as conn:
        conn.execute("CREATE TRIGGER reject_history BEFORE INSERT ON klines "
                     "BEGIN SELECT RAISE(ABORT, 'injected disk failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match="injected disk failure"):
        write_history(bar)
    assert len(kline_sources.pending(DESCRIPTOR)) == 1
