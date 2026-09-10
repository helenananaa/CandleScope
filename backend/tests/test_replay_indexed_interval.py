from decimal import Decimal
from types import SimpleNamespace
import random
import pytest

from app.replay.actor import ReplaySessionActor
from app.replay.service import ReplayService
from app.replay.errors import ReplayDomainError
from app.replay.internal_commands import InternalCommandType
from app.replay.training.storage import TrainingRunStore
from app.replay.broker.prepared_interval import EquityRanges, PreparedBarInterval
from app.replay.broker.prepared_display import PreparedDisplay
from app.replay.bars.builder import ReplayBarBuilder
from tests.fixtures.replay.bar_builder_fakes import make_replay_bar
from tests.fixtures.replay.broker_fakes import make_broker, bar, request
from tests.test_replay_interval_advance import (
    test_waiting_order_skips_safe_prefix_and_stops_at_first_fill as run_case,
)


@pytest.mark.anyio
async def test_prepare_http_endpoint_does_not_advance_or_fill(tmp_path):
    from tests.test_replay_hedge_wave_commit import seed
    from tests.test_replay_v2_training_api import _app, _request

    service, run_id, session_id = await seed(tmp_path / "prepare.db")
    try:
        before = await service.get_session_state(session_id)
        response = await _request(
            _app(service), "POST", f"/api/v1/replay/runs/{run_id}/prepare-index"
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "READY"
        after = await service.get_session_state(session_id)
        for key in ("cursor", "state_hash", "revision"):
            assert after[key] == before[key]
    finally:
        await service.shutdown(step_timeout=1)


@pytest.mark.anyio
async def test_indexed_command_recovers_without_its_final_checkpoint(
    tmp_path, monkeypatch
):
    await run_case(
        tmp_path,
        monkeypatch,
        False,
        0,
        True,
        "LONG",
        "CROSS",
        True,
        indexed=True,
        previous_checkpoint=True,
    )


@pytest.mark.anyio
async def test_indexed_hidden_time_keeps_public_projection_exact(tmp_path, monkeypatch):
    await run_case(
        tmp_path,
        monkeypatch,
        False,
        0,
        True,
        "SHORT",
        "CROSS",
        True,
        indexed=True,
        time_disclosure_policy="HIDE_ALL",
    )


@pytest.mark.anyio
async def test_review_fork_before_indexed_span_does_not_inherit_future_input(
    tmp_path, monkeypatch
):
    await run_case(
        tmp_path,
        monkeypatch,
        False,
        0,
        True,
        "SHORT",
        "CROSS",
        True,
        review_fork=True,
        indexed=True,
    )


def test_prepared_display_does_not_invent_monthly_week_components():
    from dataclasses import replace
    start = 1704067200000
    week = 7*86400000
    bars = [replace(make_replay_bar(start+i*week, '100'), close_time_ms=start+(i+1)*week-1) for i in range(10)]
    index = PreparedDisplay(bars, week, 'revision')
    result = index.query('revision', '1M', actual_start_ms=start, actual_end_ms=start+week,
                         actual_replay_start_ms=start, public_replay_start_ms=start,
                         limit=10, include_partial=True)
    assert result['bars'] == []


def test_equity_range_preserves_ordered_drawdown():
    rng = random.Random(123)
    values = [Decimal(rng.randrange(-10000, 10000)) / 100 for _ in range(513)]
    index = EquityRanges(values)
    for _ in range(200):
        start = rng.randrange(len(values))
        end = rng.randrange(start + 1, len(values) + 1)
        peak = values[start]
        drawdown = Decimal(0)
        for value in values[start:end]:
            peak = max(peak, value)
            drawdown = max(drawdown, peak - value)
        assert index.query(start, end) == (
            max(values[start:end]),
            min(values[start:end]),
            drawdown,
        )


def test_legacy_prepare_valuation_does_not_rescan_ledger_per_bar(monkeypatch):
    fast = make_broker()
    fast.place_order(request(client_order_id="open"), command_id="open")
    fast.apply_bar(bar(0, 100))
    bars = [bar(i, str(100 + (i * 7) % 31)) for i in range(1, 514)]

    class Source:
        i = 0

        def cursor(self):
            return SimpleNamespace(source_sequence=self.i + 1)

        def next(self):
            if self.exhausted():
                return None
            result = bars[self.i]
            self.i += 1
            return result

        def exhausted(self):
            return self.i == len(bars)

    index = PreparedBarInterval(
        Source(),
        fast._bar_builder,
        "sha256:" + "0" * 64,
        ReplaySessionActor._next_chain_hash,
    )
    account_from_calls = []
    original_account_from = fast._account_from

    def counting_account_from(ledger, position):
        account_from_calls.append(1)
        return original_account_from(ledger, position)

    monkeypatch.setattr(fast, "_account_from", counting_account_from)
    snapshots = {"count": 0}
    original_snapshot = fast._ledger.snapshot

    def counting_snapshot():
        snapshots["count"] += 1
        return original_snapshot()

    monkeypatch.setattr(fast._ledger, "snapshot", counting_snapshot)
    index.prepare_valuation(fast)
    assert len(account_from_calls) < len(index.bars)
    assert snapshots["count"] == 0
    cached = index.prepare_valuation(fast)
    assert cached is index.valuation
    assert snapshots["count"] == 0


def test_indexed_interval_keeps_book_funding_and_liquidation_guards():
    import inspect

    from app.replay.training.service import TrainingRunService

    source = inspect.getsource(TrainingRunService._try_indexed_interval)
    assert 'binding.get("book_mode", "OFF") != "OFF"' in source
    assert "AccountDataMode.HISTORICAL_EXACT.value" in source
    assert 'binding.get("funding_mode") not in {"OFF", "HISTORICAL_EXACT"}' in source


def test_prepared_jump_matches_sequential_broker_without_reducing_skipped_bars(
    monkeypatch,
):
    fast = make_broker()
    slow = make_broker()
    for broker in (fast, slow):
        broker.place_order(request(client_order_id="open"), command_id="open")
        broker.apply_bar(bar(0, 100))
    bars = [bar(i, str(100 + (i * 7) % 31)) for i in range(1, 514)]

    class Source:
        i = 0

        def cursor(self):
            return SimpleNamespace(source_sequence=self.i + 1)

        def next(self):
            if self.exhausted():
                return None
            result = bars[self.i]
            self.i += 1
            return result

        def exhausted(self):
            return self.i == len(bars)

    index = PreparedBarInterval(
        Source(),
        fast._bar_builder,
        "sha256:" + "0" * 64,
        ReplaySessionActor._next_chain_hash,
    )
    index.prepare_valuation(fast)
    value = index.valuation
    monkeypatch.setattr(
        fast,
        "apply_bar",
        lambda *_: (_ for _ in ()).throw(AssertionError("per-bar reducer invoked")),
    )
    for start, end in ((0, 129), (129, 300), (300, 512)):
        index.apply(fast, start, end)
        for event in bars[start:end]:
            slow.apply_bar(event)
        assert fast.snapshot() == slow.snapshot()
        assert index.prepare_valuation(fast) is value


@pytest.mark.anyio
@pytest.mark.parametrize(
    "side,margin",
    [
        ("LONG", "CROSS"),
        ("SHORT", "CROSS"),
        ("LONG", "ISOLATED"),
        ("SHORT", "ISOLATED"),
    ],
)
async def test_indexed_training_matches_financial_reference_and_recovers(
    tmp_path, monkeypatch, side, margin
):
    await run_case(
        tmp_path, monkeypatch, False, 0, True, side, margin, True, indexed=True
    )


@pytest.mark.anyio
@pytest.mark.parametrize("touch,funding", [(True, 0), (False, 180)])
async def test_indexed_training_stops_at_late_interaction(
    tmp_path, monkeypatch, touch, funding
):
    await run_case(
        tmp_path,
        monkeypatch,
        touch,
        funding,
        True,
        "LONG",
        "CROSS",
        True,
        indexed=True,
        touch_offset=180,
    )


@pytest.mark.anyio
async def test_indexed_training_refines_to_first_liquidation(tmp_path, monkeypatch):
    marks = ["100"] * 261
    marks[180:] = ["40"] * (261 - 180)
    await run_case(
        tmp_path,
        monkeypatch,
        False,
        0,
        True,
        "LONG",
        "CROSS",
        True,
        indexed=True,
        initial_equity="100",
        holding_quantity="2",
        mark_prices=marks,
        liquidation=True,
    )


@pytest.mark.anyio
async def test_indexed_flat_account_with_waiting_order(tmp_path, monkeypatch):
    await run_case(
        tmp_path, monkeypatch, False, 0, False, varying_mark=True, indexed=True
    )


@pytest.mark.anyio
async def test_indexed_jump_failure_rolls_back_all_durable_state(tmp_path, monkeypatch, shared=False):
    original_writer = TrainingRunStore._sync_indexed_trajectory
    original_command = ReplayService.command
    checked = 0

    class VerifiedRollback(RuntimeError):
        pass

    def fail(self, *args, **kwargs):
        original_writer(self, *args, **kwargs)
        raise RuntimeError("indexed write fault")

    def capture(c):
        tables = (
            "replay_session",
            "replay_training_run",
            "replay_command_log",
            "replay_checkpoint",
            "replay_training_contract_ledger",
            "replay_training_position_leg",
            "replay_training_margin_bucket",
            "replay_hedge_mark_span",
            "replay_hedge_track_public_projection",
            "replay_hedge_input_projection",
            "replay_hedge_track_public_applied_event",
            "replay_hedge_input_applied_event",
            "replay_training_global_event",
            "replay_training_global_checkpoint",
            "replay_review_timeline_event",
            "replay_interval_curve",
        )
        return {
            table: [
                tuple(row) for row in c.execute(f"SELECT * FROM {table} ORDER BY rowid")
            ]
            for table in tables
        }

    async def command(self, session_id, value, *args, **kwargs):
        nonlocal checked
        if value.type not in {InternalCommandType.INDEXED_INTERVAL, InternalCommandType.SHARED_INDEXED_INTERVAL}:
            return await original_command(self, session_id, value, *args, **kwargs)
        before = await self.store.run_extension_read(capture)
        state = await self.get_session_state(session_id)
        anchor = self._sessions[session_id].actor._shared_source_anchor
        with pytest.raises(ReplayDomainError):
            await original_command(self, session_id, value, *args, **kwargs)
        assert await self.store.run_extension_read(capture) == before
        after = await self.get_session_state(session_id)
        assert after["cursor"] == state["cursor"]
        assert after["state_hash"] == state["state_hash"]
        assert self._sessions[session_id].actor._shared_source_anchor == anchor
        checked += 1
        raise VerifiedRollback()

    monkeypatch.setattr(TrainingRunStore, "_sync_indexed_trajectory", fail)
    monkeypatch.setattr(ReplayService, "command", command)
    with pytest.raises(VerifiedRollback):
        await run_case(
            tmp_path, monkeypatch, False, 0, True, "LONG", "CROSS", True, indexed=True, shared=shared
        )
    assert checked == 1


@pytest.mark.parametrize("period,end", [("1d", 1), ("1d", 1440), ("1w", 10080)])
def test_prepared_display_matches_builder_and_never_reveals_future(period, end):
    start = 1710115200000
    bars = [
        make_replay_bar(start + i * 60000, str(100 + i % 7), volume="0.1")
        for i in range(10081)
    ]
    index = PreparedDisplay(bars, 60000, "revision")
    builder = ReplayBarBuilder(
        base_interval="1m",
        display_interval=period,
        replay_start_ms=start,
        warmup_bars=(),
    )
    builder.apply_bars_final_state(bars[:end])
    kwargs = dict(
        actual_start_ms=start,
        actual_end_ms=start + end * 60000,
        actual_replay_start_ms=start,
        public_replay_start_ms=start,
        limit=1000,
        include_partial=True,
    )
    actual = index.query("revision", period, **kwargs)
    assert actual["bars"] == builder.replace_projection()["bars"]
    assert index.query("other-revision", period, **kwargs) is None
    assert (
        index.query("revision", period, **{**kwargs, "actual_start_ms": start - 60000})
        is None
    )
