from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.data_engine.ingestion.models import DataSource, RawMessage
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
