"""Partial official listing days through old training, tape history and RSI."""

from dataclasses import replace

import pytest
from app.data_engine.storage.raw_trade_archive import RawAggTradeSelectionWindow
from app.data_preparation.bar_adapter import BarPreparationAdapter
from app.data_preparation.replay_context import ReplayHistoryContext
from app.data_preparation.replay_origin import source_key
from app.data_preparation.repository import PreparationRepository
from app.data_preparation.service import PreparationService
from app.replay.bars.builder import ReplayDisplayBar
from app.replay.catalog import ReplayCatalog, ReplaySeriesIdentity
from app.replay.dataset import validate_replay_repository_bar
from app.replay.history_archive import (
    ReplayHistoryArchiveWriter,
    ReplayHistoryRepository,
)
from app.replay.official_trade_history import (
    DAY,
    MINUTE,
    OfficialTradeHistoryRepository,
    TradeHistoryRouter,
)
from app.replay.service import ReplayService
from app.replay.storage import ReplaySQLiteStore
from app.replay.training.errors import TrainingRunError
from app.replay.training.models import TimeDisclosurePolicy, VisibleHistoryLookback
from app.replay.training.tape_chart_builder import TapeChartBuilder

from tests.fixtures.replay.fakes import make_bar
from tests.fixtures.replay.service_fakes import SessionIdFactory, replay_settings
from tests.fixtures.replay.trade_service_fakes import (
    DAY_START_MS,
    TRADE_NOW_MS,
    TRADE_REPLAY_START_MS,
)
from tests.test_replay_indicator_prefix import lines, reference
from tests.test_replay_projection_native_seam import _batch
from tests.test_replay_tape_indicator_history import ready
from tests.test_replay_tape_projection import prepare, source
from tests.test_replay_v2_training_phase5 import (
    _acquire,
    _multi_trade_sources,
    _trade_request,
)

pytestmark = pytest.mark.anyio
FIRST_DAY = DAY_START_MS - 5 * DAY
FIRST_MINUTE = FIRST_DAY + 489 * MINUTE
IDENTITY = ReplaySeriesIdentity("binance", "futures", "BTCUSDT")


class Availability:
    def list_verified_identities(self):
        return [{"exchange": "binance", "market_type": "futures", "symbol": "BTCUSDT"}]

    def selection_snapshot(self, **_):
        return "sha256:" + "a" * 64, (
            RawAggTradeSelectionWindow(FIRST_DAY, DAY_START_MS + DAY - 1, 6),
        )


def minute_row(at):
    return {
        **make_bar(at, price=str(100 + (at // MINUTE) % 19)),
        "market_type": "futures",
    }


@pytest.mark.parametrize("blind", [False, True])
@pytest.mark.parametrize("routed", [False, True])
@pytest.mark.parametrize("monthly", [False, True])
async def test_legacy_official_midnight_origin_recovers_without_account_changes(
    tmp_path, monkeypatch, blind, routed, monthly
):
    from app.replay.training import indexed_indicator_closes

    optimized_prefixes = []
    original_closes = indexed_indicator_closes.read_indexed_closes

    def observed_closes(*args, **kwargs):
        chunk = original_closes(*args, **kwargs)
        if chunk is not None and chunk.bars:
            optimized_prefixes.append((chunk.start_ms, chunk.stop_ms, len(chunk.bars)))
        return chunk

    monkeypatch.setattr(indexed_indicator_closes, "read_indexed_closes", observed_closes)
    _, tape = _multi_trade_sources(tmp_path / "tape", ("BTCUSDT",))
    downloads = []

    def download(root, identity, day):
        downloads.append(day)
        rows = [
            minute_row(at) for at in range(max(day, FIRST_MINUTE), day + DAY, MINUTE)
        ]
        ReplayHistoryArchiveWriter(root).import_batches(
            identity, "1m", [_batch(rows, source_key=str(day), digest_character="7")]
        )

    repo = OfficialTradeHistoryRepository(
        tmp_path / "official", Availability(), day_loader=None if monthly else download
    )
    if monthly:

        def download_month(root, identity, ref):
            downloads.append(ref.object_key)
            rows = [
                minute_row(at)
                for at in range(
                    max(ref.start_ms, FIRST_MINUTE),
                    min(ref.end_ms + 1, DAY_START_MS + DAY),
                    MINUTE,
                )
            ]
            ReplayHistoryArchiveWriter(root).import_batches(
                identity,
                "1m",
                [_batch(rows, source_key=ref.object_key, digest_character="7")],
            )

        monkeypatch.setattr(repo._archives, "download", download_month)
    preparation = PreparationService(
        PreparationRepository(tmp_path / "preparation.db"),
        BarPreparationAdapter(tmp_path / "chunks", coordinator=None),
    )
    await preparation.start()

    async def unexpected_origin(*_):
        pytest.fail("verified official origin must not use another provider")

    context = ReplayHistoryContext(preparation, origin_resolver=unexpected_origin)

    async def owner():
        service = ReplayService(
            settings=replace(
                replay_settings(tmp_path / "run.db"), controller_ttl_seconds=120
            ),
            store=ReplaySQLiteStore(tmp_path / "run.db", now_ms=lambda: TRADE_NOW_MS),
            repository=TradeHistoryRouter(
                ReplayHistoryRepository(tmp_path / "local"), repo
            )
            if routed
            else repo,
            raw_trade_archive=tape,
            now_ms=lambda: TRADE_NOW_MS,
            session_id_factory=SessionIdFactory("official-origin"),
            training_run_id_factory=SessionIdFactory("run"),
            native_intervals=lambda _: ("1m",),
        )
        if routed:
            # Production selects official tape availability through its own
            # catalog while the shared router retains the local BAR catalog.
            service._official_trade_catalog = ReplayCatalog(
                repo,
                native_intervals=lambda _: ("1m",),
                now_ms=lambda: TRADE_NOW_MS,
                max_scan_rows=service.settings.trade_page_rows,
                max_warmup_bars=service.settings.max_bar_dataset_rows,
                max_horizon_days=service.settings.max_horizon_days,
                max_dataset_rows=service.settings.max_bar_dataset_rows,
            )
        await service.start()
        service.history_context = context
        return service

    service = await owner()
    try:
        with monkeypatch.context() as old:
            old.setattr(
                repo, "get_history_bounds_at_revision", repo.get_bounds_at_revision
            )
            request = replace(
                await _trade_request(service),
                visible_history_lookback=VisibleHistoryLookback("ALL_AVAILABLE", None),
                time_disclosure_policy=TimeDisclosurePolicy.HIDE_ALL
                if blind
                else TimeDisclosurePolicy.NONE,
            )
            created = await service.training.create_run(request)
        run, session = created["run"]["run_id"], created["run"]["adapter_session_id"]
        await _acquire(
            service, run_id=run, selected_session_id=session, command_id="acquire"
        )
        await prepare(service, run, session)
        snapshot, _config, bars, terminal, trades = await source(service, session)
        persisted = await service.store.load_dataset(session)
        binding = await service.training.store.history_binding(
            session_id=session, track_id="track-1"
        )
        assert binding["history_policy"]["actual_visible_history_start_ms"] == FIRST_DAY
        old_origin = context.origins.pin(
            source_key(binding, persisted),
            context.origins.generation(),
            FIRST_DAY,
            FIRST_DAY,
        )
        sequence, boundary = (
            snapshot["cursor"]["source_sequence"],
            snapshot["cursor"]["virtual_time_ms"],
        )
        args = {
            "track_id": "track-1",
            "data_epoch": snapshot["data_epoch"],
            "display_interval": "90m",
            "source_sequence": sequence,
            "revealed_boundary_ms": boundary,
        }
        offset = bars.replay_start_ms - TRADE_REPLAY_START_MS
        valid_bounds = repo.get_history_bounds_at_revision
        with monkeypatch.context() as invalid:
            invalid.setattr(
                repo,
                "get_history_bounds_at_revision",
                lambda *a, **kw: {
                    **valid_bounds(*a, **kw),
                    "listing_boundary_ms": bars.warmup_rows[0].open_time_ms
                    - offset
                    + MINUTE,
                },
            )
            with pytest.raises(TrainingRunError, match="inconsistent with the Run"):
                await ready(service, session, **args, limit=12)
        scalar = TapeChartBuilder(
            base_interval="1m",
            display_interval="90m",
            replay_start_ms=bars.replay_start_ms,
            replay_end_time_ms=terminal,
            max_closed_bars=200,
            warmup_bars=tuple(
                validate_replay_repository_bar(
                    minute_row(at),
                    identity=IDENTITY,
                    interval="1m",
                    interval_ms=MINUTE,
                    expected_open_ms=at,
                    now_ms=TRADE_NOW_MS,
                ).with_time_offset(offset)
                for at in range(FIRST_MINUTE, TRADE_REPLAY_START_MS, MINUTE)
            ),
        )
        for trade in trades[:sequence]:
            scalar.apply_trades_final_state([trade])
        full = [
            ReplayDisplayBar.from_dict(row)
            for row in scalar.replace_projection()["bars"]
        ]
        full = full[1:] if not full[0].is_closed else full
        expected = lines(reference("RSI", {"period": 14}, full))
        pages, results = [], []
        for limit in (12, 35):
            page = await ready(service, session, **args, limit=limit)
            pages.append(page)
            rows = page["bars"]
            for _ in range(25):
                result = await service.training.canonical_indicator_compute(
                    session,
                    **args,
                    name="RSI",
                    params={"period": 14},
                    history_epoch=page["history_epoch"],
                    bars=rows,
                )
                if result["status"] == "ready":
                    break
            assert result["status"] == "ready"
            assert lines(result["payload"]) == [
                (
                    name,
                    [
                        point
                        for point in points
                        if point["time"] >= rows[0]["open_time_ms"] // 1000
                    ],
                )
                for name, points in expected
            ]
            results.append(result)
        assert (
            results[0]["payload"]["lines"][0]["data"][-1]
            == results[1]["payload"]["lines"][0]["data"][-1]
        )
        assert optimized_prefixes, "official full-prefix calculation did not use indexed closes"
        assert pages[0]["history_boundary_ms"] > FIRST_DAY + offset
        oldest = await ready(service, session, **args, limit=500)
        assert not oldest["has_more"]
        assert oldest["bars"][0]["first_base_open_ms"] == FIRST_MINUTE + offset
        assert oldest["bars"][0]["is_closed"] is False
        empty = await ready(
            service, session, **args, limit=500, before_ms=oldest["next_before_ms"]
        )
        assert empty["bars"] == [] and not empty["has_more"]
        assert context.origins.get(old_origin.key) == old_origin
        assert await service.store.load_dataset(session) == persisted
        assert (await service.get_session(session))["snapshot"] == snapshot
        with pytest.raises(TrainingRunError, match="generation changed"):
            await ready(
                service, session, **args, limit=12, history_epoch="sha256:" + "f" * 64
            )
        count = len(downloads)
        await service.shutdown(step_timeout=3)
        repo = OfficialTradeHistoryRepository(
            tmp_path / "official",
            Availability(),
            day_loader=lambda *_: pytest.fail("redownload on restart"),
        )
        service = await owner()
        restored = await ready(
            service, session, **args, limit=12, history_epoch=pages[0]["history_epoch"]
        )
        assert restored == pages[0] and len(downloads) == count
        restored_indicator = await service.training.canonical_indicator_compute(
            session,
            **args,
            name="RSI",
            params={"period": 14},
            history_epoch=pages[0]["history_epoch"],
            bars=pages[0]["bars"],
        )
        assert restored_indicator["status"] == "ready"
        assert restored_indicator["payload"] == results[0]["payload"]
        reopened = (await service.get_session(session))["snapshot"]
        assert reopened["controller_client_id"] is None
        assert reopened["status_reason"] == "recovered_after_restart"
        assert reopened["checkpoint_count"] >= snapshot["checkpoint_count"]
        transient = {"controller_client_id", "status_reason", "checkpoint_count"}
        assert {
            key: value for key, value in reopened.items() if key not in transient
        } == {key: value for key, value in snapshot.items() if key not in transient}
        origin = await context.origin(
            binding=binding, persisted=persisted, repository=service.history_repository
        )
        with preparation.repository.connect() as db:
            db.execute("UPDATE preparation_context_state SET generation=generation+1")
            db.execute("DELETE FROM preparation_context_origins")
        with pytest.raises(TrainingRunError, match="cache was released"):
            await context.assert_origin(origin)
        with pytest.raises(TrainingRunError, match="generation changed"):
            await ready(
                service,
                session,
                **args,
                limit=12,
                history_epoch=pages[0]["history_epoch"],
            )
        refreshed = await ready(service, session, **args, limit=12)
        assert refreshed["history_epoch"] != pages[0]["history_epoch"]
        assert refreshed["bars"] == pages[0]["bars"]
        assert refreshed["history_boundary_ms"] == pages[0]["history_boundary_ms"]
        assert (await service.get_session(session))["snapshot"] == reopened
        assert await service.store.load_dataset(session) == persisted
    finally:
        await service.shutdown(step_timeout=3)
        await preparation.shutdown()
