import hashlib
import asyncio
import threading
import json
from decimal import Decimal, localcontext
from itertools import groupby

import pytest

from app.replay.training import portfolio_history
from app.replay.training.tape_interval import restore_curve
from app.replay.training.multi_interval_store import reconstruct_portfolio_interval
from tests.test_replay_tape_phases import setup_tape, arguments


async def assert_interval_history(service, run, root):
    snapshot = await portfolio_history.capture(service.training, run)
    assert snapshot["rows"]
    for row in snapshot["rows"]:
        basis = json.loads(row[4])
        if basis["schema"] != "multi-tape-interval.v1":
            continue
        with localcontext() as ctx:
            ctx.prec = 60
            marks = {t: Decimal(p) for t, p in basis["initial_prices"].items()}

            def value():
                return Decimal(basis["cash"]) + sum(
                    (marks[leg["track_id"]] - Decimal(leg["entry"]))
                    * Decimal(leg["quantity"])
                    * (1 if leg["side"] == "LONG" else -1)
                    * Decimal(leg["rule"]["contract_size"])
                    for leg in basis["legs"]
                )

            values, points = [value()], []
            for at, events in groupby(
                sorted(basis["events"], key=lambda e: e[:4]), key=lambda e: e[0]
            ):
                for _, _, tid, _, price in events:
                    marks[tid] = Decimal(price)
                values.append(value())
                points.append((at, value()))
            rebuilt = reconstruct_portfolio_interval(
                basis, input_root=root, bucket_ms=0, limit=5000
            )
            assert [(at, Decimal(eq)) for at, eq in rebuilt["points"]] == points[-5000:]
            summary = json.loads(row[3])
            assert Decimal(summary["peak"]) == max(values)
            assert Decimal(summary["trough"]) == min(values)
            assert Decimal(summary["max_drawdown"]) == max(
                max(values[: i + 1]) - v for i, v in enumerate(values)
            )
    curve = portfolio_history.curve(snapshot, input_root=root, bucket_ms=60000)
    assert curve["available"] and curve["samples"]
    records = list(portfolio_history.export_intervals(snapshot, input_root=root))
    footer = json.loads(records[-1])
    assert footer["sha256"] == hashlib.sha256(b"".join(records[:-1])).hexdigest()
    assert footer["records"] == len(records) - 1
    assert b'"rule"' not in b"".join(records)


@pytest.mark.anyio
@pytest.mark.parametrize("track_count", [1, 2])
async def test_interval_curves_and_review_survive_reopen(tmp_path, track_count):
    service, run, sid = await setup_tape(tmp_path, held=True, track_count=track_count)
    try:
        kwargs = await arguments(service, run, sid)
        await service.training.command(run, kwargs["command"])
        await assert_interval_history(service, run, tmp_path)
        before = await service.training.equity(run, resolution="1M", limit=1000)
        review = await service.training.start_review(run, event_id=None)
        assert review
        # Reopening actors validates persisted range-end checkpoints.
        await service.shutdown(step_timeout=3)
        from tests.test_replay_v2_training_phase5 import _trade_service

        service = await _trade_service(
            tmp_path / "run.db",
            archive_root=tmp_path / "tape",
            symbols=("BTCUSDT", "ETHUSDT"),
            symbol_time_offset_ms=200,
        )
        after = await service.training.equity(run, resolution="1M", limit=1000)
        assert before == after
        await assert_interval_history(service, run, tmp_path)
        assert (await service.training.audit_account(run))["status"] == "PASS"
    finally:
        await service.shutdown(step_timeout=3)


def test_tape_curve_is_lazy_and_rejects_corrupt_range(monkeypatch):
    from app.replay.broker import shared_prepared

    basis = dict(
        schema="tape-curve.v1",
        start=1,
        times=[100, 200, 300],
        sequences=[1, 1, 2],
        prices=["90", "90", "110"],
        account=dict(cash="1000", legs=[["2", "100"]]),
        ledger_hash="ledger",
    )
    calls = shared_prepared.account_sample_visits
    restored = restore_curve(basis)
    assert shared_prepared.account_sample_visits == calls
    assert restored["samples"][2] == ("1020", "1000", "20")
    assert shared_prepared.account_sample_visits == calls + 1
    with pytest.raises(ValueError):
        restore_curve({**basis, "sequences": [1, 3, 2]})
    from app.replay.training.storage import TrainingRunStore

    payload = dict(
        schema="indexed-curve.v1",
        curve_id="curve",
        start=0,
        end=3,
        session_id="session",
        revision_base=0,
        fixed_revision=3,
        policy="NONE",
        revealed=False,
        created_at_ms=0,
    )
    interval = dict(
        command_id="interval",
        samples_json=json.dumps(payload),
        curve_json=json.dumps(basis),
        end_sequence=2,
        start_sequence=1,
        start_time_ms=100,
        end_time_ms=300,
    )
    args = dict(
        origins={"session": dict(actual_replay_start_ms=0, synthetic_origin_ms=None)},
        run_id="run",
        resolution="EVENT",
        limit=1,
    )
    rows, _ = TrainingRunStore._expand_pending_interval_curves([interval], **args)
    assert len(rows) == 1 and rows[0][3:5] == (2, 3) and rows[0][6] == "1020"
    calls = shared_prepared.account_sample_visits
    rows, _ = TrainingRunStore._expand_pending_interval_curves(
        [interval], cached={("EVENT", 2): (2, 4)}, **args
    )
    assert rows == [] and shared_prepared.account_sample_visits == calls
    with pytest.raises(ValueError, match="committed interval"):
        TrainingRunStore._expand_pending_interval_curves(
            [{**interval, "end_time_ms": 200}], **args
        )


@pytest.mark.anyio
@pytest.mark.parametrize("stage", ["summary", "records", "hashes"])
async def test_interval_preparation_leaves_sqlite_writer_available(
    tmp_path, monkeypatch, stage
):
    from app.replay.training import tape_interval, tape_phases

    service, run, sid = await setup_tape(tmp_path, held=True)
    entered, release = threading.Event(), threading.Event()
    from app.replay.training.multitrack import PreparedGlobalEventHashes
    target, method = {
        "summary": (tape_interval, "prepare_intervals"),
        "records": (tape_interval.PreparedIntervalRecord, "prepare"),
        "hashes": (PreparedGlobalEventHashes, "prepare"),
    }[stage]
    original = getattr(target, method)

    def wait(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(target, method, staticmethod(wait) if stage != "summary" else wait)
    task = None
    try:
        kwargs = await arguments(service, run, sid)
        task = asyncio.create_task(tape_phases.try_advance(service.training, **kwargs))
        assert await asyncio.to_thread(entered.wait, 5)
        assert (
            await asyncio.wait_for(
                service.store.run_extension_write(
                    lambda c: c.execute("SELECT 1").fetchone()[0]
                ),
                2,
            )
            == 1
        )
        release.set()
        assert await task is not None
    finally:
        release.set()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)
        await service.shutdown(step_timeout=3)


@pytest.mark.anyio
async def test_safe_prefix_jumps_before_a_later_liquidation(tmp_path, monkeypatch):
    from app.data_engine.storage.raw_trade_archive import ParquetRawAggTradeArchive
    from tests.fixtures.replay.trade_service_fakes import TRADE_REPLAY_START_MS
    from app.replay.training import tape_phases

    original = ParquetRawAggTradeArchive.import_verified_day

    def late_crash(archive, trades, metadata, **kwargs):
        rows = []
        for trade in trades:
            row = dict(trade)
            if (
                row["symbol"] == "BTCUSDT"
                and (row["trade_time_ms"] - TRADE_REPLAY_START_MS) // 60000 == 2
            ):
                row["price"] = 1
            row["quantity"] = 1000
            row["quote_quantity"] = row["price"] * 1000
            rows.append(row)
        return original(archive, rows, metadata, **kwargs)

    monkeypatch.setattr(ParquetRawAggTradeArchive, "import_verified_day", late_crash)
    service, run, sid = await setup_tape(tmp_path, held=True, quantity="200")
    try:
        kwargs = await arguments(service, run, sid)
        prefix = await tape_phases.try_advance(service.training, **kwargs)
        assert prefix is not None and prefix[1] < TRADE_REPLAY_START_MS + 120000
        assert not (await service.training.get_market_tracks(run))["portfolio"][
            "liquidations"
        ]
        await service.training.command(run, kwargs["command"])
        assert (await service.training.get_market_tracks(run))["portfolio"][
            "liquidations"
        ]
        assert (await service.training.audit_account(run))["status"] == "PASS"
    finally:
        await service.shutdown(step_timeout=3)
