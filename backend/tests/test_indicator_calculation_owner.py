"""Calculation ownership against actual Pine IPC; no replacement math engine."""
import asyncio
from dataclasses import replace

import pytest

from app.indicator.calculation_owner import CalculationExecution, CalculationOwnerError, CalculationPlan, ScriptCalculationOwner
from tests.test_runtime_owned_output import owner, bars, request, counter


class Harness:
    def __init__(self, tmp_path, *, max_pending=8):
        self.runtime = owner(tmp_path/'runtime.sqlite')
        self.plan = CalculationPlan('domain-chart-a', 'sha256:'+'a'*64, bars(1)[0].time)
        self.domain = ScriptCalculationOwner(self.plan, read=self.read, max_pending=max_pending)
        self.current = True
        self.released = 0

    async def read(self, reference):
        return await self.runtime.read_output(reference.stream, expected=reference)

    async def execute(self, rows, epoch):
        raw = request(rows, self.plan.owner_id)
        result = await self.runtime.execute_batch(replace(raw, options={**raw.options, 'pineSessionEpoch': epoch}))
        assert result.ok, result.diagnostics
        held = await self.runtime.read_output(self.plan.owner_id)
        return CalculationExecution(held.reference, result.meta['sessionRetained'], result.meta['sessionReset'])

    async def submit(self, rows, *, rebuild=False, revision='source:1', execute=None):
        async def actual(epoch): return await self.execute(rows, epoch)
        return await self.domain.advance(semantic_identity=self.plan.semantic_identity, input_start=rows[0].time,
            observed_through=rows[-1].time, closed_through=max((row.time for row in rows if row.is_closed), default=0),
            input_revision=revision, expected=self.domain.cursor, rebuild=rebuild,
            is_current=lambda: self.current, execute=execute or actual)

    async def release(self): self.released += 1

    async def close(self):
        await self.domain.close(release=self.release)
        await self.runtime.stop()


@pytest.mark.anyio
async def test_chart_range_reads_never_shorten_or_advance_the_retained_calculation(tmp_path):
    h = Harness(tmp_path)
    try:
        seeded = await h.submit(bars(500))
        assert seeded.generation == seeded.sequence == 1
        first = await h.submit(bars(501, forming=True))
        assert first.generation == 1 and first.sequence == 2
        before = h.runtime.snapshot()['requests']
        for _ in range(10): assert counter((await h.domain.read(expected=first)).output) == 501
        assert h.runtime.snapshot()['requests'] == before
        with pytest.raises(CalculationOwnerError, match='CLOCK_REGRESSED'): await h.submit(bars(200))
        assert h.runtime.snapshot()['requests'] == before
        with pytest.raises(CalculationOwnerError, match='CHANGED'): await h.domain.read(expected=seeded)
        # This is a real subsequent forming update with a slid transport
        # window; the retained mathematical prefix still starts at the origin.
        rows = bars(501, forming=True)
        rows = (*rows[:-1], replace(rows[-1], close=103))[-201:]
        second = await h.submit(rows)
        assert second.generation == 1 and counter((await h.domain.read(expected=second)).output) == 502
        # A declared rebuild forces a fresh runtime epoch, even if BAR contents
        # did not change. It must not count the same forming observation twice.
        rebuilt = await h.submit(bars(501, forming=True), rebuild=True)
        assert rebuilt.generation == 2
        assert counter((await h.domain.read(expected=rebuilt)).output) == 501
    finally: await h.close()


@pytest.mark.anyio
async def test_changed_source_revision_requires_full_origin_and_new_generation(tmp_path):
    h = Harness(tmp_path)
    try:
        old = await h.submit(bars(500))
        before = h.runtime.snapshot()['requests']
        with pytest.raises(CalculationOwnerError, match='REBUILD_REQUIRED'):
            await h.submit(bars(500), revision='source:2')
        with pytest.raises(CalculationOwnerError, match='ORIGIN_REQUIRED'):
            await h.submit(bars(500)[-201:], revision='source:2', rebuild=True)
        assert h.runtime.snapshot()['requests'] == before
        changed = bars(500)
        changed = (*changed[:10], replace(changed[10], close=101), *changed[11:])
        current = await h.submit(changed, revision='source:2', rebuild=True)
        assert current.generation == old.generation+1 and current.input_revision == 'source:2'
        assert counter((await h.domain.read(expected=current)).output) == 500
        with pytest.raises(CalculationOwnerError, match='CHANGED'): await h.domain.read(expected=old)
    finally: await h.close()


@pytest.mark.anyio
async def test_source_fence_after_actual_execution_refuses_publication_and_requires_rebuild(tmp_path):
    h = Harness(tmp_path)
    try:
        old = await h.submit(bars(500))
        async def changed_during_execution(epoch):
            result = await h.execute(bars(501, forming=True), epoch)
            h.current = False
            return result
        with pytest.raises(CalculationOwnerError, match='SOURCE_CHANGED'):
            await h.submit(bars(501, forming=True), execute=changed_during_execution)
        assert h.domain.cursor == old
        with pytest.raises(CalculationOwnerError, match='REBUILD_REQUIRED'): await h.domain.read(expected=old)
        h.current = True
        with pytest.raises(CalculationOwnerError, match='REBUILD_REQUIRED'): await h.submit(bars(501, forming=True))
        current = await h.submit(bars(501, forming=True), rebuild=True)
        assert current.generation == old.generation+1 and counter((await h.domain.read(expected=current)).output) == 501
    finally: await h.close()


@pytest.mark.anyio
@pytest.mark.parametrize('cancel_close', [False, True])
async def test_cancelled_waiter_keeps_physical_ownership_and_close_drains_before_release(tmp_path, cancel_close):
    h = Harness(tmp_path, max_pending=1)
    entered, release = asyncio.Event(), asyncio.Event()
    async def held(epoch):
        result = await h.execute(bars(500), epoch)
        entered.set(); await release.wait()
        return result
    pending = asyncio.create_task(h.submit(bars(500), execute=held))
    try:
        await asyncio.wait_for(entered.wait(), 10)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError): await pending
        with pytest.raises(CalculationOwnerError, match='BUSY'): await h.submit(bars(500))
        closing = asyncio.create_task(h.domain.close(release=h.release))
        await asyncio.sleep(0)
        assert not closing.done() and h.released == 0 and h.domain.cursor is None
        if cancel_close:
            closing.cancel(); await asyncio.sleep(0)
            assert not closing.done() and h.released == 0
        with pytest.raises(CalculationOwnerError, match='CLOSED'): await h.submit(bars(500))
        release.set()
        if cancel_close:
            with pytest.raises(asyncio.CancelledError): await asyncio.wait_for(closing, 10)
        else: await asyncio.wait_for(closing, 10)
        assert h.released == 1 and h.domain.cursor.sequence == 1
        await h.domain.close(release=h.release)
        assert h.released == 1
    finally:
        release.set(); await h.close()


@pytest.mark.anyio
async def test_lost_replica_never_turns_a_read_into_runtime_restart_or_short_reseed(tmp_path):
    h = Harness(tmp_path)
    try:
        old = await h.submit(bars(500))
        before = h.runtime.snapshot()['starts']
        await h.runtime.stop()
        with pytest.raises(CalculationOwnerError, match='OUTPUT_LOST'): await h.domain.read(expected=old)
        assert h.runtime.snapshot()['starts'] == before
        with pytest.raises(CalculationOwnerError, match='ORIGIN_REQUIRED'):
            await h.submit(bars(500)[-201:], rebuild=True)
        current = await h.submit(bars(500), rebuild=True)
        assert current.generation == 2 and counter((await h.domain.read(expected=current)).output) == 500
    finally: await h.close()


@pytest.mark.anyio
async def test_nonoverlapping_tail_reset_is_not_published_as_the_previous_calculation(tmp_path):
    h = Harness(tmp_path)
    try:
        old = await h.submit(bars(500))
        with pytest.raises(CalculationOwnerError, match='ORIGIN_REQUIRED'):
            await h.submit(bars(601)[-50:])
        assert h.domain.cursor == old
        with pytest.raises(CalculationOwnerError, match='REBUILD_REQUIRED'): await h.domain.read(expected=old)
        current = await h.submit(bars(601), rebuild=True)
        assert current.generation == old.generation+1
        assert counter((await h.domain.read(expected=current)).output) == 601
    finally: await h.close()


@pytest.mark.anyio
async def test_wrong_output_owner_and_unapplied_rebuild_never_become_current(tmp_path):
    h = Harness(tmp_path)
    epoch = None
    rows = bars(20, forming=True)
    async def remember_epoch(value):
        nonlocal epoch
        epoch = value
        return await h.execute(rows, value)
    try:
        old = await h.submit(rows, execute=remember_epoch)
        async def ignore_rebuild(_value): return await h.execute(rows, epoch)
        with pytest.raises(CalculationOwnerError, match='REBUILD_NOT_APPLIED'):
            await h.submit(rows, rebuild=True, execute=ignore_rebuild)
        assert h.domain.cursor == old
        current = await h.submit(rows, rebuild=True)
        assert current.generation == 2 and counter((await h.domain.read(expected=current)).output) == 20
        async def wrong_stream(value):
            result = await h.runtime.execute_batch(replace(request(rows, 'other-owner'), options={'pineSessionId':'other-owner','pineSessionEpoch':value}))
            held = await h.runtime.read_output('other-owner')
            return CalculationExecution(held.reference, result.meta['sessionRetained'], result.meta['sessionReset'])
        with pytest.raises(CalculationOwnerError, match='OUTPUT_IDENTITY_CHANGED'):
            await h.submit(rows, execute=wrong_stream)
        assert h.domain.cursor == current
        with pytest.raises(CalculationOwnerError, match='REBUILD_REQUIRED'): await h.domain.read(expected=current)
    finally: await h.close()
