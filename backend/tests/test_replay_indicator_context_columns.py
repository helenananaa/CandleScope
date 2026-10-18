"""Indicator-only context must never replace the full chart's cached columns."""

from threading import Event

import pytest
from app.replay.dataset import ReplayBar
from app.replay.training.tape_projection import TapeDisplayProjection

from tests.test_replay_tape_phases import setup_tape
from tests.test_replay_tape_projection import prepare, source
from tests.test_replay_tape_projection_incremental import ready


@pytest.mark.anyio
@pytest.mark.parametrize("indicator_first", [False, True])
async def test_context_column_modes_stay_separate_across_forward_cache_reuse(
    tmp_path, indicator_first
):
    service, run, session = await setup_tape(tmp_path)
    try:
        await prepare(service, run, session)
        snapshot, _, frozen, _, trades = await source(service, session)
        stop = frozen.warmup_rows[0].open_time_ms
        modes = []

        class Context:
            origin_ms = stop - 40 * 60000
            history_epoch = "sha256:" + "d" * 64

            def read_indexed(
                self, start, end, interval, cancelled, *, include_auxiliary=True
            ):
                modes.append(include_auxiliary)
                optional = ("202", 7, "1", "101") if include_auxiliary else (None,) * 4
                return end, tuple(
                    (
                        ReplayBar(
                            at,
                            at + 59999,
                            "100",
                            "102",
                            "99",
                            "101",
                            "2",
                            *optional,
                            "replay_context",
                        ),
                        at,
                        1,
                    )
                    for at in range(start, end, 60000)
                )

        common = {
            "binding": await service.training.store.history_binding(
                session_id=session, track_id="track-1"
            ),
            "persisted": await service.store.load_dataset(session),
            "archive": service.raw_trade_archive,
            "data_epoch": snapshot["data_epoch"],
            "cancelled": Event(),
            "context_history": Context(),
            "display_interval": "7m",
            "limit": 12,
        }
        shared = TapeDisplayProjection()
        for sequence in (1, 2):
            request = dict(
                common,
                source_sequence=sequence,
                revealed_boundary_ms=trades[sequence - 1].trade_time_ms,
            )
            full = ready(TapeDisplayProjection(), **request)
            reduced = ready(TapeDisplayProjection(), **request, indicator_input=True)
            assert any(row["quote_volume"] is not None for row in full["bars"])
            assert any(row["quote_volume"] is None for row in reduced["bars"])
            for actual, expected in zip(reduced["bars"], full["bars"], strict=True):
                assert {
                    k: v
                    for k, v in actual.items()
                    if k
                    not in (
                        "quote_volume",
                        "trades",
                        "taker_buy_base",
                        "taker_buy_quote",
                    )
                } == {
                    k: v
                    for k, v in expected.items()
                    if k
                    not in (
                        "quote_volume",
                        "trades",
                        "taker_buy_base",
                        "taker_buy_quote",
                    )
                }
            for indicator in (indicator_first, not indicator_first):
                assert ready(shared, **request, indicator_input=indicator) == (
                    reduced if indicator else full
                )
        assert True in modes and False in modes
        assert (await service.get_session(session))["snapshot"] == snapshot
    finally:
        await service.shutdown(step_timeout=3)
