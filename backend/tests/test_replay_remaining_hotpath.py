from __future__ import annotations

from dataclasses import replace

import pytest

from app.replay.bars.builder import ReplayBarBuilder
from app.replay.broker.execution import BROKER_STATE_SCHEMA_VERSION
from app.replay.broker.models import (
    OrderSide,
    PositionMode,
    PositionSide,
    TOUCH_OR_TAPE_EXECUTION_MODE,
)
from app.replay.broker.prepared_interval import PreparedBarInterval
from app.replay.broker.shared_prepared import (
    account_sample,
    restore_curve,
)
from app.replay.canonical import canonical_json
from app.replay.shared_market_index import MarketRange
from app.replay.source_chain import next_source_chain_hash
from tests.fixtures.replay.broker_fakes import CONFIG, bar, make_broker, request
from tests.fixtures.replay.service_fakes import START_MS
from tests.test_replay_hotpath_history import _history_broker, _seed_live_book
from tests.test_replay_prepared_cache import Source, fixture as prepared_fixture
from tests.test_replay_shared_market_index import market


def test_full_snapshot_restore_keeps_existing_archive_contract():
    live, index = _seed_live_book(20)
    base = live.snapshot()
    live.place_order(request(client_order_id="extra", side=OrderSide.SELL), command_id="extra")
    live.apply_bar(bar(index, 101))
    current = live.snapshot()
    assert current["schema_version"] == BROKER_STATE_SCHEMA_VERSION
    restored = _history_broker()
    restored.restore(current)
    assert restored.snapshot() == current
    restored.restore(base)
    assert restored.snapshot() == base


def test_legacy_prepare_defers_builder_and_account_work_until_advance():
    broker, bars = prepared_fixture()
    ReplayBarBuilder.final_state_bar_visits = 0
    from app.replay.broker import shared_prepared
    before_samples = shared_prepared.account_sample_visits
    index = PreparedBarInterval(
        Source(bars),
        broker._bar_builder,
        "sha256:" + "0" * 64,
        next_source_chain_hash,
    )
    index.prepare_valuation(broker)
    assert ReplayBarBuilder.final_state_bar_visits == 0
    assert shared_prepared.account_sample_visits == before_samples
    assert len(index.bars) == len(bars)

    slow = make_broker()
    slow.place_order(request(client_order_id="open"), command_id="open")
    slow.apply_bar(bar(0, 100))
    end = 64
    index.apply(broker, 0, end)
    for event in bars[:end]:
        slow.apply_bar(event)
    assert broker.fills == slow.fills
    assert broker.account.cash_balance == slow.account.cash_balance
    assert broker.position.to_dict() == slow.position.to_dict()
    assert broker._bar_builder.replay_events_applied == slow._bar_builder.replay_events_applied

    ranged = PreparedBarInterval(
        Source(bars[:8]),
        make_broker()._bar_builder,
        "sha256:" + "0" * 64,
        None,
    )
    hashed = PreparedBarInterval(
        Source(bars[:8]),
        make_broker()._bar_builder,
        "sha256:" + "0" * 64,
        next_source_chain_hash,
    )
    assert ranged.chains[3] != hashed.chains[3]
    expected = hashed.chains[3]
    hashed.materialize_legacy_chains()
    assert hashed.chains[3] == expected


def test_two_close_commands_execute_against_unchanged_depth():
    broker = make_broker(config=replace(CONFIG, position_mode=PositionMode.HEDGE),
                         execution_mode=TOUCH_OR_TAPE_EXECUTION_MODE)
    broker.place_order(replace(request(client_order_id="long"), position_side=PositionSide.LONG), command_id="long")
    broker.apply_bar(bar(0, 100))
    levels = [{"price": "99", "quantity": "0.5"}]
    orders = []
    for number in range(2):
        orders.append(broker.execute_historical_book_close(
            position_side="LONG", side="SELL", quantity="0.5", levels=levels,
            command_id=f"close-{number}", accepted_source_sequence=broker._bar_builder.replay_events_applied,
            created_time_ms=0,
        ))
    assert orders[0].order_id != orders[1].order_id
    assert broker.position.long.quantity == "0"
    assert broker.historical_book_reuses == 1
    assert len(broker.fills) == 3


@pytest.mark.anyio
async def test_chunked_hourly_curve_visits_selected_offsets_only(tmp_path):
    from tests.test_replay_hedge_wave_commit import seed

    service, run_id, session_id = await seed(tmp_path / "curve1600.db")
    try:
        count, chunk, limit = 96_000, 8_000, 1_600
        index_dir = tmp_path / "idx"
        index_dir.mkdir()
        obj, base = market(index_dir, count)
        view = MarketRange(base.parts, offset_ms=START_MS)
        account = {"legs": [["1", "100"]], "cash": "10000"}
        basis = {
            "schema": "shared-curve.v1",
            "market": view.descriptor(),
            "reference": view.reference(),
            "start": 0,
            "seed": "sha256:" + "0" * 64,
            "account": account,
            "ledger_hash": "sha256:" + "1" * 64,
        }

        def insert(connection):
            connection.execute(
                "DELETE FROM replay_equity_sample WHERE run_id=?", (run_id,)
            )
            connection.execute(
                "INSERT INTO replay_prepared_curve VALUES (?, ?, ?)",
                ("curve-1600", run_id, canonical_json(basis)),
            )
            for start in range(0, count, chunk):
                payload = {
                    "schema": "indexed-curve.v1",
                    "curve_id": "curve-1600",
                    "start": start,
                    "end": start + chunk,
                    "session_id": session_id,
                    "revision_base": start,
                    "policy": "NONE",
                    "revealed": True,
                    "created_at_ms": 0,
                }
                connection.execute(
                    """
                    INSERT INTO replay_interval_curve(
                        run_id, command_id, end_sequence, samples_json,
                        start_sequence, start_time_ms, end_time_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        str(start),
                        start + chunk,
                        canonical_json(payload),
                        start + 1,
                        int(view.row(start)[1]),
                        int(view.row(start + chunk - 1)[1]),
                    ),
                )

        await service.store.run_extension_write(insert)
        from app.replay.broker import shared_prepared

        shared_prepared.account_sample_visits = 0
        MarketRange.row_visits = 0
        MarketRange.block_loads = 0
        result = await service.training.equity(run_id, resolution="1H", limit=limit)
        samples = result["samples"]
        assert result["resolution"] == "1H"
        assert 1 <= len(samples) <= limit
        assert shared_prepared.account_sample_visits == len(samples)
        assert MarketRange.row_visits < count
        assert MarketRange.block_loads <= len(samples)
        restored = restore_curve(basis)
        for sample in samples:
            offset = int(sample["source_sequence"]) - restored["start"] - 1
            expected = account_sample(account, view.row(offset)[5])
            assert sample["equity"] == expected[0]
    finally:
        await service.shutdown(step_timeout=1)


def test_legacy_market_summary_reads_only_boundary_blocks(monkeypatch):
    from app.replay.broker.prepared_interval import _BarListMarket
    from app.replay.shared_market_index import summarize
    bars = [bar(i, 100 + i % 17) for i in range(10_000)]
    market = _BarListMarket(bars, 60000)
    expected = summarize([market.row(i) for i in range(17, 9901)], 60000)
    original = market.row
    visits = []
    def row(i):
        visits.append(i)
        return original(i)
    monkeypatch.setattr(market, "row", row)
    assert market.summary(17, 9901) == expected
    assert len(visits) < 512


def test_prepared_cache_save_does_not_materialize_chains_or_samples(tmp_path, monkeypatch):
    from app.replay.broker.prepared_cache import prepare
    from app.replay.broker import shared_prepared
    broker, bars = prepared_fixture()
    calls = []
    def chain(*args):
        calls.append(1)
        return next_source_chain_hash(*args)
    before = shared_prepared.account_sample_visits
    index = prepare(Source(bars), broker, "sha256:" + "0" * 64, chain, tmp_path / "market.cache")
    assert calls == []
    assert shared_prepared.account_sample_visits == before
    basis = index.curve_basis()
    assert basis["schema"] == "prepared-curve.v2"
    assert calls == []
    assert shared_prepared.account_sample_visits == before
    from app.replay.broker.shared_prepared import restore_legacy_curve
    restored = restore_legacy_curve(basis)
    end = min(16, len(bars))
    assert restored["chains"][end] == index.chains[end]
    assert len(calls) == end
    assert restored["samples"][end-1] == index.valuation["samples"][end-1]
