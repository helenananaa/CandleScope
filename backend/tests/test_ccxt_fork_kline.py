"""Contract tests for the opt-in pinned CCXT fork (offline, no credentials)."""

from __future__ import annotations

import asyncio
import copy
import json
import os
from contextlib import asynccontextmanager

import ccxt.async_support as ccxt_async
import pytest

from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.models import (
    DataSource,
    RawMessage,
    StreamDescriptor,
    StreamType,
    TransportRequest,
)
from app.exchanges.ccxt_ext.binance_usdm import CandleScopeBinanceUSDM
from app.exchanges.ccxt_ext.primary import create_binance_ccxt_plugin
from app.exchanges.ccxt_ext.profiles.binance_usdm import BinanceUsdmCcxtProfile

MARKET = dict(
    id="BTCUSDT",
    symbol="BTC/USDT:USDT",
    base="BTC",
    quote="USDT",
    settle="USDT",
    type="swap",
    swap=True,
    spot=False,
    contract=True,
    linear=True,
    inverse=False,
)
ROW = [
    1769904000000,
    "100.000000000000001",
    "103",
    "99",
    "102",
    "10",
    1772323199999,
    "1010",
    4,
    "6",
    "606",
    "0",
]
DESCRIPTOR = StreamDescriptor(
    "BTCUSDT", StreamType.KLINE, interval="1M", market_type="futures"
)
FRAME = dict(
    e="kline",
    E=1772323200001,
    s="BTCUSDT",
    k=dict(
        t=ROW[0],
        T=ROW[6],
        s="BTCUSDT",
        i="1M",
        o=ROW[1],
        h=ROW[2],
        l=ROW[3],
        c=ROW[4],
        v=ROW[5],
        q=ROW[7],
        n=ROW[8],
        V=ROW[9],
        Q=ROW[10],
        x=False,
    ),
)


def fork_exchange():
    exchange = ccxt_async.binanceusdm()
    exchange.set_markets([MARKET])
    if not hasattr(exchange, "parse_candlescope_kline"):
        if os.environ.get("CANDLESCOPE_REQUIRE_CCXT_FORK") == "1":
            pytest.fail("fork qualification requires the pinned generated wheel")
        pytest.skip(
            "requires backend/scripts/install_ccxt_fork.py; vanilla regression suite remains supported"
        )
    return exchange


def parse(payload, source=DataSource.HTTP, received=1772323200001):
    plugin = create_binance_ccxt_plugin()
    return plugin.normalizer(IngestionConfig(), DESCRIPTOR).parse(
        RawMessage(payload, source, StreamType.KLINE, received)
    )


def test_release_defaults_to_fork_and_rollback_runtime_is_partitioned(monkeypatch):
    monkeypatch.delenv("INGESTION_CCXT_FORK_KLINE_ENABLED", raising=False)
    plain = IngestionConfig(ccxt_fork_kline_enabled=False)
    enabled = IngestionConfig()
    assert enabled.ccxt_fork_kline_enabled is True
    profile = BinanceUsdmCcxtProfile()
    assert profile.runtime_key(plain) != profile.runtime_key(enabled)


def test_fork_guard_rejects_unqualified_build():
    from app.exchanges.ccxt_ext.fork_kline import require_fork
    from app.exchanges.ccxt_ext import CcxtCompatibilityError

    with pytest.raises(CcxtCompatibilityError, match="fork"):
        require_fork(object())


def test_rest_month_close_and_source_decimal_evidence():
    exchange = fork_exchange()
    payload = exchange.parse_candlescope_kline(ROW, MARKET, "1M")
    event = parse(payload)
    assert event.data["close_time"] == 1772323199999
    assert event.data["is_closed"] is True
    assert event.data["close_evidence"] == "rest_close_time_elapsed"
    assert event.data["quote_volume"] == 1010
    assert event.data["taker_buy_base"] == 6
    assert event.data["trades"] == 4
    assert json.loads(event.data["source_candle"]["raw"])[1] == ROW[1]
    assert parse(payload, received=ROW[6]).data["is_closed"] is False


@pytest.mark.parametrize(
    "field,value",
    [
        ("quoteVolume", None),
        ("open", "NaN"),
        ("close", "1e10000"),
        ("volume", "-1"),
        ("trades", True),
        ("trades", 1.5),
        ("high", "90"),
        ("volumeUnit", "contracts"),
        ("marketId", "ETHUSDT"),
        ("timeframe", "1m"),
        ("closeTime", 0),
        ("takerBuyBaseVolume", "11"),
        ("schema", "candlescope.binance.usdm.kline.v2"),
    ],
)
def test_invalid_or_mismatched_data_is_rejected(field, value):
    exchange = fork_exchange()
    payload = exchange.parse_candlescope_kline(ROW, MARKET, "1M")
    payload[field] = value
    with pytest.raises(ValueError):
        parse(payload)


def test_raw_hook_and_normalizer_preserve_ws_revisions(monkeypatch):
    fork_exchange()
    from ccxt.pro.binanceusdm import binanceusdm

    monkeypatch.setattr(binanceusdm, "handle_ohlcv", lambda *args: "projected")
    captured = []
    driver = CandleScopeBinanceUSDM(
        raw_event_sink=captured.append, fork_kline_enabled=True
    )
    driver.set_markets([MARKET])
    frame = copy.deepcopy(FRAME)
    assert driver.handle_ohlcv(object(), frame) == "projected"
    frame["k"]["q"] = "1011"
    driver.handle_ohlcv(object(), frame)
    frame["k"]["x"] = True
    driver.handle_ohlcv(object(), frame)
    frame["k"]["n"] = 5
    driver.handle_ohlcv(object(), frame)
    assert len(captured) == 4
    profile = BinanceUsdmCcxtProfile()
    assert all(profile.matches(event, DESCRIPTOR) for event in captured)
    events = [parse(event.payload, DataSource.WEBSOCKET) for event in captured]
    assert [event.data["quote_volume"] for event in events] == [1010, 1011, 1011, 1011]
    assert [event.data["is_closed"] for event in events] == [False, False, True, True]
    assert [event.data["trades"] for event in events] == [4, 4, 4, 5]
    assert all(event.data["close_evidence"] == "ws_x" for event in events)
    assert json.loads(captured[0].payload["raw"])["k"]["q"] == "1010"


def test_parser_coercion_cannot_hide_malformed_source_trades():
    exchange = fork_exchange()
    raw = list(ROW)
    raw[8] = 4.5
    with pytest.raises(ValueError, match="source evidence"):
        parse(exchange.parse_candlescope_kline(raw, MARKET, "1M"))


def test_ws_forming_candle_is_not_promoted_by_local_clock():
    exchange = fork_exchange()
    payload = exchange.parse_candlescope_ws_kline(FRAME)
    assert (
        parse(payload, DataSource.WEBSOCKET, received=ROW[6] + 86400000).data[
            "is_closed"
        ]
        is False
    )


def test_rest_finality_uses_pre_request_exchange_clock_when_present():
    payload = fork_exchange().parse_candlescope_kline(ROW, MARKET, "1M")
    payload["_source_rest_server_time_ms"] = ROW[6]
    assert not parse(payload, received=ROW[6] + 86400000).data["is_closed"]
    payload["_source_rest_server_time_ms"] = ROW[6] + 1
    event = parse(payload, received=ROW[6] - 86400000)
    assert event.data["is_closed"]
    assert event.data["close_evidence"] == "rest_server_time_elapsed"


def test_python_fork_1500_rows_and_concurrent_requests_are_independent():
    exchange = fork_exchange()
    started = asyncio.Event()

    async def fetch(params):
        if params["startTime"] == 0:
            started.set()
            await asyncio.sleep(0)
        else:
            await started.wait()
        return [[params["startTime"] + i * 60000, *ROW[1:]] for i in range(1500)]

    exchange.fapiPublicGetKlines = fetch

    async def run():
        try:
            return await asyncio.gather(
                exchange.fetch_candlescope_klines(MARKET["symbol"], "1m", 0, 1500),
                exchange.fetch_candlescope_klines(MARKET["symbol"], "1m", 60000, 1500),
            )
        finally:
            await exchange.close()

    first, second = asyncio.run(run())
    assert len(first) == len(second) == 1500
    assert first[0]["timestamp"] == 0
    assert second[0]["timestamp"] == 60000
    assert first[0]["raw"] != second[0]["raw"]


@pytest.mark.parametrize("history_projection", [False, True])
def test_primary_uses_fork_rest_method_with_1500_and_shared_pool(monkeypatch, tmp_path, history_projection):
    from app.data_engine.storage import klines_repo, kline_sources
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", tmp_path / "klines.sqlite")
    klines_repo.init_klines_storage()
    exchange = fork_exchange()
    calls = []

    async def fetch(params):
        calls.append(params)
        return [ROW]

    exchange.fapiPublicGetKlines = fetch
    async def server_time(params):
        return ROW[6] + 1
    exchange.fetch_time = server_time

    class Pool:
        @asynccontextmanager
        async def request(self, selection):
            assert selection == "swap.linear"
            yield exchange

        async def resolve_symbol(self, *args, **kwargs):
            return MARKET["symbol"]

    plugin = create_binance_ccxt_plugin()
    monkeypatch.setattr(plugin.provider, "_rest_pool", lambda venue, config: Pool())

    async def run():
        try:
            return await plugin.fetch_history_with_config(
                TransportRequest(
                    DESCRIPTOR, limit=2000, start_ms=ROW[0], end_ms=ROW[6],
                    history_projection=history_projection,
                ),
                IngestionConfig(ccxt_fork_kline_enabled=True),
            )
        finally:
            await exchange.close()

    messages = asyncio.run(run())
    assert calls == [
        dict(
            symbol="BTCUSDT",
            interval="1M",
            limit=1500,
            startTime=ROW[0],
            endTime=ROW[6],
        )
    ]
    assert messages[0].request_limit == 1500
    assert messages[0].payload["_source_delivery_owner"] == ("history" if history_projection else "market")
    assert bool(kline_sources.pending(DESCRIPTOR)) is not history_projection
    assert len(kline_sources.pending(DESCRIPTOR, include_history=True)) == 1
    assert parse(messages[0].payload).data["quote_volume"] == 1010


def test_numeric_fields_round_trip_through_isolated_sqlite(tmp_path, monkeypatch):
    from app.data_engine.storage import klines_repo

    exchange = fork_exchange()
    event = parse(exchange.parse_candlescope_kline(ROW, MARKET, "1M"))
    database = tmp_path / "fork-klines.sqlite"
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", database)
    klines_repo.init_klines_storage()
    klines_repo.upsert_klines(
        "BTCUSDT",
        "1M",
        [event.data],
        source="rest",
        exchange="binance",
        market_type="futures",
    )
    # query_klines opens its own SQLite connection; no cached BarData is involved.
    rows = klines_repo.query_klines(
        "BTCUSDT", "1M", exchange="binance", market_type="futures"
    )
    assert len(rows) == 1
    for field in (
        "close_time",
        "quote_volume",
        "trades",
        "taker_buy_base",
        "taker_buy_quote",
    ):
        assert rows[0][field] == event.data[field]
    # The prototype does not claim durable storage of the complete evidence envelope.
    assert "source_candle" not in rows[0]


def test_guard_rejects_a_different_source_pin(tmp_path, monkeypatch):
    from app.exchanges.ccxt_ext import CcxtCompatibilityError
    from app.exchanges.ccxt_ext import fork_kline

    exchange = fork_exchange()
    lock = json.loads(fork_kline.LOCK_PATH.read_text())
    lock["source_commit"] = "0" * 40
    path = tmp_path / "lock.json"
    path.write_text(json.dumps(lock))
    monkeypatch.setattr(fork_kline, "LOCK_PATH", path)
    with pytest.raises(CcxtCompatibilityError, match="source commit"):
        fork_kline.require_fork(exchange)


def test_competing_deferred_pages_reuse_proven_clock_without_losing_their_turn(monkeypatch, tmp_path):
    """Clock -> Kline pairs must progress when another chunk protects its turn."""
    from app.data_engine.storage import klines_repo
    from app.exchanges.public_admission import PublicAdmission, PublicDemand, TrafficClass, current_demand, public_demand
    from app.exchanges.rate_limits import HistoricalRequest, RateLimitDeferred, RateLimitManager, RateLimitRule
    monkeypatch.setattr(klines_repo, 'KLINES_DB_PATH', tmp_path / 'clock-pages.sqlite')
    klines_repo.init_klines_storage()
    exchange = fork_exchange()
    admission = PublicAdmission(RateLimitManager())
    quota = RateLimitRule('shared', 'shared', 100, 3600)
    first, second = [PublicDemand(TrafficClass.INTERACTIVE, defer=True) for _ in range(2)]
    clocks, pages = [], []
    async def physical(endpoint):
        permit = await admission.acquire([quota], HistoricalRequest('binance', 'futures', endpoint, 'BTCUSDT'),
                                         demand=current_demand())
        permit.finish(status_code=200)
    async def server_time(params):
        await physical('/fapi/v1/time')
        clocks.append(params)
        if len(clocks) == 1:
            admission.protect(second, quota.bucket_key)
        return ROW[6] + 1
    async def fetch(params):
        await physical('/fapi/v1/klines')
        pages.append(params)
        return [ROW]
    exchange.fetch_time = server_time
    exchange.fapiPublicGetKlines = fetch
    class Pool:
        @asynccontextmanager
        async def request(self, selection):
            yield exchange
        async def resolve_symbol(self, *args, **kwargs):
            return MARKET['symbol']
    plugin = create_binance_ccxt_plugin()
    monkeypatch.setattr(plugin.provider, '_rest_pool', lambda venue, config: Pool())
    request = TransportRequest(DESCRIPTOR, limit=1, start_ms=ROW[0], end_ms=ROW[6], history_projection=True)
    async def fetch_page(demand, req=request):
        with public_demand(demand):
            return await plugin.fetch_history_with_config(req, IngestionConfig(ccxt_fork_kline_enabled=True))
    async def run():
        try:
            with pytest.raises(RateLimitDeferred, match='critical_demand'):
                await fetch_page(first)
            admission.protect(first, quota.bucket_key)
            admission.forget(second)
            result = await fetch_page(second)
            assert len(result) == 1
            admission.forget(first)
            assert len(await fetch_page(first)) == 1
            assert len(clocks) == 1 and len(pages) == 2
            # A later requested boundary and unbounded latest read each need
            # fresh server time; old observations cannot confirm a new bucket.
            from dataclasses import replace
            await fetch_page(first, replace(request, end_ms=ROW[6] + 1))
            await fetch_page(first, replace(request, end_ms=None))
            assert len(clocks) == 3
        finally:
            await exchange.close()
    asyncio.run(run())


def test_snapshot_clock_proof_respects_market_and_complete_calendar_bucket():
    from dataclasses import replace
    from types import SimpleNamespace
    from app.exchanges.ccxt_ext.venue_history import _binance_snapshot_time

    calls = []
    async def clock(params):
        calls.append(params)
        return ROW[6] + 1
    exchange = SimpleNamespace(fetch_time=clock)
    req = TransportRequest(DESCRIPTOR, end_ms=ROW[6])
    async def run():
        assert await _binance_snapshot_time(exchange, req, futures=True) == ROW[6] + 1
        # Both the month's last millisecond and an earlier timestamp in the
        # same month are bounded by the same proven calendar close.
        await _binance_snapshot_time(exchange, replace(req, end_ms=ROW[0]), futures=True)
        assert len(calls) == 1
        await _binance_snapshot_time(exchange, req, futures=False)
        assert len(calls) == 2 and calls[-1] == {'type': 'spot'}
        for end in (ROW[6] + 1, None, True, -1):
            await _binance_snapshot_time(exchange, replace(req, end_ms=end), futures=True)
        unknown = replace(req, descriptor=replace(DESCRIPTOR, interval='unknown'))
        await _binance_snapshot_time(exchange, unknown, futures=True)
        assert len(calls) == 7
        # Equality with the close is insufficient: the exchange must have
        # advanced beyond the whole bucket, with no local-clock inference.
        exchange._candlescope_snapshot_times['futures'] = ROW[6]
        await _binance_snapshot_time(exchange, req, futures=True)
        assert len(calls) == 8
        assert set(exchange._candlescope_snapshot_times) == {'spot', 'futures'}
    asyncio.run(run())
