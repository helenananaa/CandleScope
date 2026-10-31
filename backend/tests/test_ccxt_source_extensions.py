"""Cross-venue source fidelity, archive recovery and historical re-fetch tests."""

import asyncio
import copy
import json
import os
from contextlib import closing

import ccxt.async_support as ccxt
import pytest

from app.data_engine.ingestion.config import IngestionConfig
from app.data_engine.ingestion.models import (
    DataSource,
    RawMessage,
    StreamDescriptor,
    StreamType,
)
from app.data_engine.ingestion.normalize import NormalizeLayer
from app.data_engine.storage import (
    klines_repo,
    kline_sources,
    market_sources,
    source_retention,
    source_enrichment,
)
from app.exchanges.ccxt_ext.fork_kline import (
    normalize_fork_kline,
    prepare_source_messages,
)
from app.exchanges.ccxt_ext.source_capture import (
    REST_CAPTURE,
    RestSourceCaptureMixin,
    RAW_ONLY,
)

ROW = [
    "1772323200000",
    "100.000000000000001",
    "103",
    "99",
    "102",
    "100",
    "1",
    "101",
    "1",
]
SWAP = dict(
    id="BTC-USDT-SWAP",
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
SPOT = dict(
    SWAP,
    id="BTC-USDT",
    symbol="BTC/USDT",
    type="spot",
    swap=False,
    spot=True,
    contract=False,
)


@pytest.fixture(autouse=True)
def qualified_fork():
    if not hasattr(ccxt.okx, "parse_candlescope_kline"):
        if os.environ.get("CANDLESCOPE_REQUIRE_CCXT_FORK") == "1":
            pytest.fail("Install qualified Binance/OKX fork wheel")
        pytest.skip("requires the opt-in qualified Binance/OKX fork wheel")


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.setattr(klines_repo, "KLINES_DB_PATH", tmp_path / "klines.sqlite")
    klines_repo.init_klines_storage()


def okx_message(spot=False, ws=False, row=None):
    ex = ccxt.okx()
    if not hasattr(ex, "parse_candlescope_kline"):
        pytest.fail("Install qualified Binance/OKX fork wheel")
    market = SPOT if spot else SWAP
    ex.set_markets([market])
    row = row or ROW
    payload = (
        ex.parse_candlescope_ws_klines(
            {"arg": {"channel": "candle1m", "instId": market["id"]}, "data": [row]}
        )[0]
        if ws
        else ex.parse_candlescope_kline(row, market, "1m")
    )
    desc = StreamDescriptor(
        market["id"],
        StreamType.KLINE,
        interval="1m",
        exchange="okx",
        market_type="spot" if spot else "futures",
    )
    return desc, RawMessage(
        payload,
        DataSource.WEBSOCKET if ws else DataSource.HTTP,
        StreamType.KLINE,
        int(ROW[0]) + 60010,
    )


@pytest.mark.parametrize("spot", [False, True])
@pytest.mark.parametrize("ws", [False, True])
def test_okx_units_and_missing_fields(database, spot, ws):
    desc, msg = okx_message(spot, ws)
    event = normalize_fork_kline(msg, desc)
    assert event.data["volume"] == (100 if spot else 1)
    assert event.data["quote_volume"] == 101
    assert event.data["trades"] is None and event.data["taker_buy_base"] is None
    assert set(event.data["enhanced_fields"]) == {"volume", "quote_volume"}
    assert event.data["close_time"] == int(ROW[0]) + 59999
    asyncio.run(
        prepare_source_messages([msg], desc, watermark=kline_sources.rest_watermark())
    )
    head = kline_sources.latest(desc, int(ROW[0]))
    assert head["envelope"]["open"] == ROW[1]
    assert head["ws_event_time"] is None


@pytest.mark.parametrize("spot", [False, True])
def test_okx_closed_history_with_unknown_fields_reaches_reconciler(database, spot):
    from app.data_engine.backfill.config import BackfillConfig
    from app.data_engine.backfill.fetcher import HistoricalFetcher
    from app.data_engine.backfill.models import BackfillTask, BackfillPlan, FetchResult
    from app.data_engine.backfill.reconciler import Reconciler

    async def run():
        desc, message = okx_message(spot=spot)
        await prepare_source_messages([message], desc, watermark=kline_sources.rest_watermark())
        message.source = DataSource.HTTP_BACKFILL
        event = NormalizeLayer(IngestionConfig(), desc).parse_raw(message)
        assert event is not None and event.data["is_closed"]
        task = BackfillTask(symbol=desc.symbol, interval=desc.interval, exchange=desc.exchange,
                            market_type=desc.market_type, start_ms=int(ROW[0]), end_ms=int(ROW[0]))
        bar = HistoricalFetcher._event_to_bar(event, task)
        assert bar is not None, "unknown enhanced fields must not discard valid OHLCV"
        assert bar.enhanced_fields == frozenset({"quote_volume"})
        result = await Reconciler(BackfillConfig(), klines_repo.AsyncKlinesRepoAdapter()).reconcile(
            [FetchResult(task=task, bars=[bar])], BackfillPlan(gaps=[]))
        assert result.bars_written == 1 and not result.errors
        rows = klines_repo.KlinesRepoAdapter().query_bars(
            symbol=desc.symbol, interval=desc.interval, exchange=desc.exchange,
            market_type=desc.market_type, start_ms=int(ROW[0]), end_ms=int(ROW[0]))
        assert len(rows) == 1 and rows[0]["close"] == 102
        assert rows[0]["volume"] == (100 if spot else 1)
        assert rows[0]["quote_volume"] == 101
        assert all(rows[0][name] is None for name in ("trades", "taker_buy_base", "taker_buy_quote"))
        assert not kline_sources.pending(desc)
        replayed = []
        replay = NormalizeLayer(IngestionConfig(ccxt_fork_kline_enabled=True), desc)
        async def receive(event):
            replayed.append(event)
        replay.on_event(receive)
        await replay.replay_source_pending()
        assert replayed == []

    asyncio.run(run())


def test_okx_unordered_closed_change_requires_rest(database):
    desc, msg = okx_message(ws=True)
    asyncio.run(prepare_source_messages([msg], desc))
    changed = ROW.copy()
    changed[7] = "100"
    _, later = okx_message(ws=True, row=changed)
    asyncio.run(prepare_source_messages([later], desc))
    assert later.payload["_source_receipt"]["status"] == "reconcile"
    assert kline_sources.latest(desc, int(ROW[0]))["data"]["quote_volume"] == 101


def test_raw_only_frame_is_saved_before_projection_and_not_parsed(database):
    async def run():
        desc = StreamDescriptor(
            "BTC-USDT-SWAP", StreamType.DEPTH, exchange="okx", market_type="futures"
        )
        layer = NormalizeLayer(IngestionConfig(ccxt_fork_kline_enabled=True), desc)
        frame = {
            "arg": {"channel": "books", "instId": desc.symbol},
            "action": "update",
            "data": [
                {
                    "seqId": 12,
                    "prevSeqId": 11,
                    "checksum": 123,
                    "bids": [["100.000000000000001", "2", "0", "4"]],
                }
            ],
        }
        msg = RawMessage(
            {RAW_ONLY: True, "raw": frame}, DataSource.WEBSOCKET, StreamType.DEPTH, 100
        )
        await layer.ingest(msg)
        rows = market_sources.observations(desc)
        assert json.loads(rows[0]["payload_json"]) == frame
        report = source_retention.compact(now_ms=100 * 86400000)
        assert report["archived"] == 1
        assert market_sources.observations(desc) == rows

    asyncio.run(run())


def test_rest_capture_is_task_local_and_keeps_outer_envelope():
    class Base:
        async def fetch(self, url, method, headers, body):
            await asyncio.sleep(0)
            return {
                "code": "0",
                "data": [{"price": "1.000000000000001"}],
                "msg": "",
                "request": url[-1],
            }

    class Exchange(RestSourceCaptureMixin, Base):
        pass

    async def one(i):
        frames = []
        token = REST_CAPTURE.set(frames)
        try:
            await Exchange().fetch(f"https://public.test/data?item={i}")
        finally:
            REST_CAPTURE.reset(token)
        assert len(frames) == 1 and frames[0]["payload"]["request"] == str(i)
        assert frames[0]["endpoint"] == "https://public.test/data"

    async def run():
        await asyncio.gather(one(1), one(2))

    asyncio.run(run())


def test_archive_preserves_heads_history_and_rejects_corruption(database):
    desc, msg = okx_message()
    asyncio.run(
        prepare_source_messages([msg], desc, watermark=kline_sources.rest_watermark())
    )
    first = copy.deepcopy(msg)
    _, second = okx_message(row=[*ROW[:7], "102", "1"])
    asyncio.run(
        prepare_source_messages(
            [second], desc, watermark=kline_sources.rest_watermark()
        )
    )
    before = kline_sources.observations(desc, int(ROW[0]))
    report = source_retention.compact(now_ms=int(ROW[0]) + 100 * 86400000)
    assert report["archived"] == 1
    assert kline_sources.observations(desc, int(ROW[0])) == before
    assert len(kline_sources.pending(desc)) == 1
    asyncio.run(prepare_source_messages([first], desc, watermark=0))
    assert len(kline_sources.observations(desc, int(ROW[0]))) == 2
    with closing(klines_repo._connect()) as conn, conn:
        conn.execute("UPDATE source_log_archives SET sha256='invalid'")
    with pytest.raises(RuntimeError, match="checksum"):
        kline_sources.observations(desc, int(ROW[0]))


def test_archive_rollback_preserves_hot_payload(database, monkeypatch):
    desc, msg = okx_message()
    market_sources.record_rest(
        desc, [{"received_at": 0, "endpoint": "public", "payload": ROW}]
    )

    def fail(*args):
        raise OSError("injected disk failure")

    monkeypatch.setattr(source_retention, "restore_row", fail)
    with pytest.raises(OSError):
        source_retention.compact(now_ms=100 * 86400000)
    with closing(klines_repo._connect()) as conn:
        assert conn.execute(
            "SELECT payload_json FROM market_source_observations"
        ).fetchone()[0]
        assert (
            conn.execute("SELECT COUNT(*) FROM source_log_archives").fetchone()[0] == 0
        )


def test_enrichment_backup_survives_delivery_failure_and_retry(database):
    async def run():
        desc, msg = okx_message()
        data = normalize_fork_kline(msg, desc).data
        old = dict(data, close=100)
        klines_repo.upsert_klines(
            desc.symbol, desc.interval, [old], exchange="okx", market_type="futures"
        )

        class Plugin:
            async def fetch_history_with_config(self, req, config):
                _, value = okx_message()
                await prepare_source_messages(
                    [value], desc, watermark=kline_sources.rest_watermark()
                )
                return [value]

        async def fail(message):
            raise OSError("delivery failed")

        config = IngestionConfig(ccxt_fork_kline_enabled=True)
        args = dict(start_ms=int(ROW[0]), end_ms=int(ROW[0]))
        with pytest.raises(OSError):
            await source_enrichment.enrich(desc, config, Plugin(), fail, **args)

        async def deliver(message):
            head = kline_sources.latest(desc, int(ROW[0]))
            klines_repo.upsert_klines(
                desc.symbol,
                desc.interval,
                [head["data"]],
                exchange="okx",
                market_type="futures",
            )
            kline_sources.acknowledge(message.payload["_source_receipt"]["ref"])

        result = await source_enrichment.enrich(desc, config, Plugin(), deliver, **args)
        assert result["revised"] == 1
        with closing(klines_repo._connect()) as conn:
            audit = conn.execute("SELECT * FROM source_enrichment_audit").fetchone()
            assert json.loads(audit["original_json"])["close"] == 100
            assert (
                audit["evidence_origin"] == "historical_refetch"
                and audit["status"] == "revised"
            )

    asyncio.run(run())


@pytest.mark.parametrize("spot", [False, True])
def test_okx_real_delivery_path_acknowledges_revisions(database, spot):
    from scripts.validate_ccxt_source_matrix import Harness

    async def run():
        desc, msg = okx_message(spot=spot)
        harness = Harness(desc, IngestionConfig(ccxt_fork_kline_enabled=True))
        try:
            await prepare_source_messages(
                [msg], desc, watermark=kline_sources.rest_watermark()
            )
            await harness.deliver(msg)
            assert not kline_sources.pending(desc)
            revised = ROW.copy()
            revised[7] = "102"
            _, changed = okx_message(spot=spot, row=revised)
            await prepare_source_messages(
                [changed], desc, watermark=kline_sources.rest_watermark()
            )
            await harness.deliver(changed)
            assert not kline_sources.pending(desc)
            rows = klines_repo.query_klines(
                desc.symbol, desc.interval, exchange="okx", market_type=desc.market_type
            )
            assert rows[0]["quote_volume"] == 102 and rows[0]["trades"] is None
        finally:
            await harness.close()

    asyncio.run(run())


def test_public_clients_scope_bootstrap_and_use_current_okx_ws_port():
    from app.exchanges.ccxt_ext.profiles.okx_spot import OkxSpotCcxtProfile
    from app.exchanges.ccxt_ext.profiles.okx_swap import OkxSwapCcxtProfile
    from app.exchanges.ccxt_ext.generic import CcxtUnifiedProfile
    from app.exchanges.ccxt_ext.catalog import get_ccxt_catalog_entry

    config = IngestionConfig(ccxt_fork_kline_enabled=True)
    for profile, types in [
        (OkxSpotCcxtProfile(), ["spot"]),
        (OkxSwapCcxtProfile(), ["swap"]),
        (
            CcxtUnifiedProfile(get_ccxt_catalog_entry("okx"), "futures"),
            ["spot", "swap"],
        ),
    ]:
        ex = profile.create_exchange(config, raw_event_sink=None, lifecycle_sink=None)
        assert ex.options["fetchMarkets"]["types"] == types
        assert ex.urls["api"]["ws"] == "wss://ws.okx.com/ws/v5"


def test_enrichment_batches_consecutive_rows_without_claiming_gaps(database):
    async def run():
        desc, _ = okx_message()
        stamps = [int(ROW[0]), int(ROW[0]) + 60000, int(ROW[0]) + 180000]
        for stamp in stamps:
            row = ROW.copy()
            row[0] = str(stamp)
            _, msg = okx_message(row=row)
            data = normalize_fork_kline(msg, desc).data
            klines_repo.upsert_klines(
                desc.symbol, "1m", [data], exchange="okx", market_type="futures"
            )
        calls = []

        class Plugin:
            async def fetch_history_with_config(self, req, config):
                calls.append((req.start_ms, req.end_ms, req.limit))
                messages = []
                for stamp in stamps:
                    if req.start_ms <= stamp <= req.end_ms:
                        row = ROW.copy()
                        row[0] = str(stamp)
                        messages.append(okx_message(row=row)[1])
                await prepare_source_messages(
                    messages, desc, watermark=kline_sources.rest_watermark()
                )
                return messages

        async def deliver(msg):
            kline_sources.acknowledge(msg.payload["_source_receipt"]["ref"])

        result = await source_enrichment.enrich(
            desc,
            IngestionConfig(ccxt_fork_kline_enabled=True),
            Plugin(),
            deliver,
            start_ms=stamps[0],
            end_ms=stamps[-1],
        )
        assert result["matched"] == 3
        assert calls == [(stamps[0], stamps[1], 2), (stamps[2], stamps[2], 1)]

    asyncio.run(run())


@pytest.mark.parametrize("legacy,previously_delivered", [(False, False), (True, False), (True, True)])
def test_offline_enrichment_cli_handles_sparse_binance_history(database, monkeypatch, legacy, previously_delivered):
    from types import SimpleNamespace
    import app.exchanges
    from scripts.enrich_ccxt_sources import run
    from tests.test_ccxt_fork_kline import MARKET, fork_exchange

    desc = StreamDescriptor(
        "BTCUSDT", StreamType.KLINE, interval="1m", exchange="binance", market_type="futures"
    )
    stamps = [int(ROW[0]), int(ROW[0]) + 180000]
    ex = fork_exchange()

    def message(stamp):
        raw = [stamp, "100", "103", "99", "102", "10", stamp + 59999,
               "1010", 4, "6", "606", "0"]
        payload = ex.parse_candlescope_kline(raw, MARKET, "1m")
        payload["_source_rest_server_time_ms"] = stamps[-1] + 60000
        return RawMessage(payload, DataSource.HTTP, StreamType.KLINE, stamps[-1] + 60000)

    for stamp in stamps:
        original = dict(normalize_fork_kline(message(stamp), desc).data, close=100)
        klines_repo.upsert_klines(
            desc.symbol, "1m", [original], exchange="binance", market_type="futures"
        )

    if previously_delivered:
        async def record_old_heads():
            values = [message(stamp) for stamp in stamps]
            await prepare_source_messages(values, desc, watermark=kline_sources.rest_watermark())
            for value in values:
                kline_sources.acknowledge(value.payload["_source_receipt"]["ref"])
        asyncio.run(record_old_heads())

    legacy_before = None
    if legacy:
        with closing(klines_repo._connect()) as conn, conn:
            conn.execute("DROP TABLE bar_basis_migrations")
            legacy_before = conn.execute("SELECT * FROM klines ORDER BY open_time").fetchall()
        klines_repo.init_klines_storage()
        assert not klines_repo.query_klines(desc.symbol, "1m", exchange="binance", market_type="futures")
        assert len(source_enrichment.candidate_rows(
            desc, start_ms=stamps[0], end_ms=stamps[-1], legacy=True,
        )) == 2

    async def fetch_history(req, config):
        assert req.start_ms == req.end_ms and req.start_ms in stamps
        values = [message(req.start_ms)]
        await prepare_source_messages(values, desc, watermark=kline_sources.rest_watermark())
        return values

    app.exchanges.bootstrap_default_adapters()
    plugin = app.exchanges.get_exchange_registry().get_plugin("binance")
    monkeypatch.setattr(plugin, "fetch_history_with_config", fetch_history)
    args = SimpleNamespace(
        symbol=desc.symbol, interval="1m", exchange="binance", market="futures",
        start=stamps[0], end=stamps[-1], limit=300, apply=True,
        legacy=legacy, data_dir=klines_repo.KLINES_DB_PATH.parent,
    )
    args.apply = False
    assert asyncio.run(run(args))["rows"] == 2
    args.apply = True
    if previously_delivered:
        async def drop_delivery(self, message):
            pass

        with monkeypatch.context() as patch:
            patch.setattr(NormalizeLayer, "ingest", drop_delivery)
            with pytest.raises(RuntimeError, match="qualified enrichment projection is still missing"):
                asyncio.run(run(args))
    result = asyncio.run(run(args))
    assert result["revised"] == 2
    if legacy:
        with closing(klines_repo._connect()) as conn:
            assert conn.execute("SELECT * FROM klines_legacy_basis_v1 ORDER BY open_time").fetchall() == legacy_before
    assert not kline_sources.pending(desc)
    with closing(klines_repo._connect()) as conn:
        audits = conn.execute("SELECT original_json,status FROM source_enrichment_audit").fetchall()
    assert len(audits) == 2
    assert all(json.loads(row[0])["close"] == 100 and row[1] == "revised" for row in audits)
    stored = klines_repo.query_klines(desc.symbol, "1m", exchange="binance", market_type="futures")
    assert [row["open_time"] for row in stored] == stamps
    assert all(row["close"] == 102 for row in stored)
    assert asyncio.run(run(args))["already_evidenced"] == 2
