from __future__ import annotations

import json
from dataclasses import replace
from threading import Event

import pytest
from app.data_engine.storage.raw_trade_archive import (
    ParquetRawAggTradeArchive,
    VerifiedRawAggTradeDay,
)
from app.replay.bars.builder import ReplayDisplayBar
from app.replay.bars.trade_builder import TradeReplayBarBuilder
from app.replay.sources.trade_reader import PagedReplayTradeReader, ReplayTrade
from app.replay.training.indicator_history import IndicatorHistoryChunk
from app.replay.training.tape_chart_builder import TapeChartBuilder
from app.replay.training.tape_projection import TapeDisplayProjection

from tests.fixtures.replay.trade_fakes import make_trade_row
from tests.test_replay_tape_phases import setup_tape
from tests.test_replay_tape_projection import (
    frontend_oracle,
    prepare,
    scalar_base,
    source,
)

pytestmark = pytest.mark.anyio


async def test_advancing_observers_resume_closed_context_without_reusing_future_selection(
    tmp_path,
):
    service, run, session = await setup_tape(tmp_path)
    try:
        await prepare(service, run, session)
        snapshot, _, frozen, _, trades = await source(service, session)
        persisted = await service.store.load_dataset(session)
        binding = await service.training.store.history_binding(
            session_id=session, track_id="track-1"
        )
        stop = frozen.warmup_rows[0].open_time_ms
        reads = []

        class Context:
            origin_ms = stop - 40 * 60000
            history_epoch = "sha256:" + "d" * 64

            def read(self, start, end):
                reads.append(start)
                end = min(end, start + 10 * 60000)
                rows = tuple(
                    ReplayDisplayBar.from_dict(
                        {
                            "open_time_ms": at,
                            "close_time_ms": at + 59999,
                            "open": "100",
                            "high": "102",
                            "low": "99",
                            "close": "101",
                            "volume": "2",
                            "quote_volume": None,
                            "trades": None,
                            "taker_buy_base": None,
                            "taker_buy_quote": None,
                            "first_base_open_ms": at,
                            "last_base_open_ms": at,
                            "component_count": 1,
                            "expected_components": 1,
                            "is_closed": True,
                            "synthetic": False,
                        }
                    )
                    for at in range(start, end, 60000)
                )
                return IndicatorHistoryChunk(start, end, rows, ())

        context = Context()
        projection = TapeDisplayProjection(pages_per_call=1)
        common = {
            "binding": binding,
            "persisted": persisted,
            "archive": service.raw_trade_archive,
            "data_epoch": snapshot["data_epoch"],
            "display_interval": "1m",
            "before_ms": stop,
            "limit": 500,
            "context_history": context,
            "cancelled": Event(),
            "include_selection_boundary": True,
        }
        results = []
        for sequence in range(4):
            results.append(
                projection.compute(
                    **common,
                    source_sequence=sequence,
                    revealed_boundary_ms=frozen.replay_start_ms - 1
                    if sequence == 0
                    else trades[sequence - 1].trade_time_ms,
                )
            )
        assert [row["status"] for row in results] == ["preparing"] * 3 + ["ready"]
        assert reads == list(range(context.origin_ms, stop, 10 * 60000))
        assert len(results[-1]["bars"]) == 40
        # A cached later observation must never prove that an earlier selection
        # consumed the same closed tape prefix, even if its clock is later.
        early = projection.compute(
            **common, source_sequence=0, revealed_boundary_ms=trades[2].trade_time_ms
        )
        assert early["status"] == "ready" and early["bars"] == results[-1]["bars"]
        assert (
            early["selected_closed_before_ms"]
            == results[0]["selected_closed_before_ms"]
        )
        assert (
            early["selected_closed_before_ms"]
            < results[-1]["selected_closed_before_ms"]
        )
        assert len(reads) == 4
        assert not projection._owners
        assert (await service.get_session(session))["snapshot"] == snapshot
    finally:
        await service.shutdown(step_timeout=3)


@pytest.mark.parametrize("page_size", [1, 3, 17, 8192])
async def test_chart_decimal_accumulators_match_scalar_on_each_page(page_size):
    start = 1_780_272_000_000
    scalar = TradeReplayBarBuilder(
        base_interval="1m",
        display_interval="1m",
        replay_start_ms=start,
        replay_end_time_ms=start + 240_000 - 1,
    )
    chart = TapeChartBuilder(
        base_interval="1m",
        display_interval="1m",
        replay_start_ms=start,
        replay_end_time_ms=start + 240_000 - 1,
    )
    trades = []
    for index in range(101):
        trade = ReplayTrade.from_archive_row(
            make_trade_row(index, trade_time_ms=start + (index // 34) * 60_000 + 1000)
        )
        # Both much wider than precision 60 and tiny fractional additions must
        # retain the scalar reducer's rounding/order across request boundaries.
        quantity = (
            "9" * 70
            if index % 13 == 0
            else "0." + "0" * 69 + "1"
            if index % 5 == 0
            else "0.123456789123456789"
        )
        trades.append(replace(trade, quantity=quantity, quote_quantity=quantity))
    for offset in range(0, len(trades), page_size):
        part = trades[offset : offset + page_size]
        for trade in part:
            scalar.apply_trade(trade)
        chart.apply_trades_final_state(part)
        expected = scalar.replace_projection()["bars"]
        assert chart.replace_projection()["bars"] == expected
        assert chart.replace_projection()["bars"] == expected
    scalar.finalize_bars(virtual_time_ms=start + 240_000 - 1)
    chart.finalize_bars(virtual_time_ms=start + 240_000 - 1)
    assert chart.replace_projection()["bars"] == scalar.replace_projection()["bars"]


async def test_sparse_pages_close_only_with_revealed_evidence_and_survive_cache_loss(
    tmp_path,
):
    service, _, session = await setup_tape(tmp_path)
    try:
        _, config, bars, terminal, _ = await source(service, session)
        archive = ParquetRawAggTradeArchive(tmp_path / "sparse", max_rows_per_file=1)
        rows = [
            make_trade_row(
                i, trade_time_ms=bars.replay_start_ms + minute * 60_000 + 1000
            )
            for i, minute in enumerate((0, 3))
        ]
        archive.import_verified_day(
            rows,
            VerifiedRawAggTradeDay(
                exchange="binance",
                market_type="futures",
                symbol="BTCUSDT",
                date="2026-06-01",
                source_url="https://fixture.invalid/trades.zip",
                source_file="trades.zip",
                source_checksum_sha256="a" * 64,
                row_count=2,
                first_agg_trade_id=100,
                last_agg_trade_id=101,
                first_trade_time_ms=rows[0]["trade_time_ms"],
                last_trade_time_ms=rows[1]["trade_time_ms"],
            ),
        )
        reference = archive.freeze_dataset(
            exchange="binance",
            market_type="futures",
            symbol="BTCUSDT",
            start_time_ms=bars.replay_start_ms,
            end_time_ms=terminal,
        )
        persisted = dict(await service.store.load_dataset(session))
        payload = json.loads(persisted["snapshot_blob"])
        payload["trade_dataset_ref"] = reference.to_dict()
        persisted.update(
            data_epoch=reference.data_epoch, snapshot_blob=json.dumps(payload).encode()
        )
        binding = dict(
            await service.training.store.history_binding(
                session_id=session, track_id="track-1"
            )
        )
        binding.update(
            source_sequence=2,
            virtual_time_ms=terminal,
            track_dataset_epoch=reference.data_epoch,
            session_data_epoch=reference.data_epoch,
            run_dataset_epoch=reference.data_epoch,
        )
        trades = tuple(PagedReplayTradeReader(archive, reference).iter_trades())
        arguments = {
            "binding": binding,
            "persisted": persisted,
            "archive": archive,
            "data_epoch": reference.data_epoch,
            "limit": 1,
            "cancelled": Event(),
        }
        projection = TapeDisplayProjection(page_rows=1, pages_per_call=1, capacity=1)
        cases = []
        for boundary in (trades[-1].trade_time_ms, terminal):
            for interval in ("1m", "2m", "7m", "90m"):
                before = None
                collected = []
                for _ in range(10):
                    request = dict(
                        **arguments,
                        display_interval=interval,
                        source_sequence=2,
                        revealed_boundary_ms=boundary,
                        before_ms=before,
                    )
                    for _ in range(5):
                        page = projection.compute(**request)
                        if page["status"] == "ready":
                            break
                    assert page["status"] == "ready"
                    assert (
                        all(row["open_time_ms"] < before for row in page["bars"])
                        if before is not None
                        else True
                    )
                    # A cold cache must reconstruct exactly the same page, not
                    # depend on having fetched the later or immediately prior page.
                    cold = TapeDisplayProjection().compute(**request)
                    assert cold == page
                    collected = page["bars"] + collected
                    if not page["has_more"]:
                        exhausted = projection.compute(
                            **{**request, "before_ms": page["next_before_ms"]}
                        )
                        assert (
                            exhausted["bars"] == [] and exhausted["has_more"] is False
                        )
                        break
                    assert before is None or page["next_before_ms"] < before
                    before = page["next_before_ms"]
                else:
                    pytest.fail("sparse tape pages did not terminate")
                if interval == "1m":
                    gaps = [
                        row
                        for row in collected
                        if row["open_time_ms"]
                        in (
                            bars.replay_start_ms + 60_000,
                            bars.replay_start_ms + 120_000,
                        )
                    ]
                    assert len(gaps) == 2
                    assert all(
                        row["is_closed"]
                        and row["synthetic"]
                        and row["volume"] == "0"
                        and row["close"] == "100"
                        for row in gaps
                    )
                cases.append(
                    {
                        "base": config.base_interval,
                        "interval": interval,
                        "limit": 100,
                        "rows": scalar_base(
                            config, bars, terminal, trades, 2, boundary
                        ),
                        "actual": collected,
                    }
                )
        await frontend_oracle(tmp_path, cases)
        # Merely selecting a later clock without consuming the later trade
        # cannot close the earlier forming minute or invent intervening rows.
        first_only = TapeDisplayProjection().compute(
            **{**arguments, "limit": 10},
            display_interval="1m",
            source_sequence=1,
            revealed_boundary_ms=trades[-1].trade_time_ms,
        )
        assert first_only["bars"][-1]["open_time_ms"] == bars.replay_start_ms
        assert first_only["bars"][-1]["is_closed"] is False
    finally:
        await service.shutdown(step_timeout=3)
