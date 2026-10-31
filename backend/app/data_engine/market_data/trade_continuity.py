"""Subscriber-local ID repair over TradeFlow's shared repair and retained ring."""
from __future__ import annotations

import asyncio
import time
from dataclasses import replace

from app.data_engine.consumer_recovery import ConsumerRecoveryRequired
from app.data_engine.continuity_policy import ContinuityPolicy
from .append_hub import AppendBatch


class TradeContinuitySubscription:
    def __init__(self, subscription, service, identities, policy):
        self.inner, self.service = subscription, service
        self.policy = ContinuityPolicy.resolve(policy)
        self.limit = subscription._max_pending_records
        self.cursors = {
            identity: tail[-1].agg_trade_id if (tail := service.engine.raw_tail(identity, 1)) else None
            for identity in identities
        }
        self._watches = []
        self._sequence = 0
        self._reading = None
        self._terminal = None
        ranges = []
        if self.policy.mode == "gap_aware":
            for identity in identities:
                for gap in service.engine.gap_snapshot(identity):
                    ranges.append({"identity": identity, "start_id": gap.start_id, "end_id": gap.end_id})
                    retained = sum(end - start + 1 for _, start, end in self._watches)
                    if retained + gap.missing_count <= self.limit:
                        self._watches.append((identity, gap.start_id, gap.end_id))
                    else:
                        ranges[-1]["error"] = "source_gap_tracking_exhausted"
        self._initial = AppendBatch(0, (), continuity=False, resync_required=True, detail={
            "source_continuity": {"state": "gapped", "guarantee": "monotonic_id", "ranges": ranges},
        }) if ranges else None

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def _rows(self, identity, start, end):
        return tuple(row for row in self.service.engine.raw_snapshot(identity)
                     if start <= row.agg_trade_id <= end)

    async def _repair(self, identity, start, end, deadline):
        if end - start + 1 > self.limit:
            raise ConsumerRecoveryRequired("source_gap_exceeds_replay_limit")
        while True:
            changed = self.service._continuity_changed
            rows = self._rows(identity, start, end)
            if [row.agg_trade_id for row in rows] == list(range(start, end + 1)):
                return rows
            if self.inner.closed or self.service._closed:
                raise ConsumerRecoveryRequired("source_stream_closed")
            if identity in self.service._degraded_identities:
                raise ConsumerRecoveryRequired("source_repair_failed")
            if not any(gap.start_id <= end and gap.end_id >= start
                       for gap in self.service.engine.gap_snapshot(identity)):
                raise ConsumerRecoveryRequired("source_gap_history_exhausted")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ConsumerRecoveryRequired("source_gap_timeout")
            try:
                await asyncio.wait_for(changed.wait(), remaining)
            except TimeoutError:
                raise ConsumerRecoveryRequired("source_gap_timeout") from None

    def _corrections(self):
        corrected, resolved, failed, remaining = [], [], [], []
        for identity, start, end in self._watches:
            rows = self._rows(identity, start, end)
            item = {"identity": identity, "start_id": start, "end_id": end}
            if [row.agg_trade_id for row in rows] == list(range(start, end + 1)):
                corrected.extend(rows)
                resolved.append(item)
            elif identity in self.service._degraded_identities or not any(
                gap.start_id <= end and gap.end_id >= start
                for gap in self.service.engine.gap_snapshot(identity)
            ):
                failed.append(item)
            else:
                remaining.append((identity, start, end))
        self._watches = remaining
        if resolved or failed:
            return AppendBatch(self._sequence, (), corrections=tuple(corrected), detail={
                "source_continuity": {
                    "state": "failed" if failed else "resolved",
                    "guarantee": "monotonic_id", "resolved": resolved, "failed": failed,
                },
            })
        return None

    async def receive(self):
        try:
            while True:
                if self._terminal is not None:
                    raise self._terminal
                if self._initial is not None:
                    initial, self._initial = self._initial, None
                    return initial
                changed = self.service._continuity_changed
                if self.policy.mode == "gap_aware":
                    correction = self._corrections()
                    if correction is not None:
                        return correction
                if self._reading is None:
                    self._reading = asyncio.create_task(self.inner.receive())
                notification = asyncio.create_task(changed.wait())
                try:
                    await asyncio.wait({self._reading, notification}, return_when=asyncio.FIRST_COMPLETED)
                    if not self._reading.done():
                        continue
                    batch = self._reading.result()
                    self._reading = None
                finally:
                    notification.cancel()
                    await asyncio.gather(notification, return_exceptions=True)
                if batch is None:
                    return None
                self._sequence = batch.sequence
                deadline = time.monotonic() + self.policy.max_wait_seconds
                output, ranges, replayed = [], [], False
                for record in batch.records:
                    identity, current = record.stream_identity, record.agg_trade_id
                    previous = self.cursors[identity]
                    if previous is not None and current <= previous:
                        continue
                    if previous is None and not batch.continuity and self.policy.mode == "strict":
                        raise ConsumerRecoveryRequired("source_gap_snapshot_required")
                    if previous is not None and current > previous + 1:
                        start, end = previous + 1, current - 1
                        ranges.append({"identity": identity, "start_id": start, "end_id": end})
                        if self.policy.mode == "strict":
                            output.extend(await self._repair(identity, start, end, deadline))
                            replayed = True
                        elif sum(upper - lower + 1 for _, lower, upper in self._watches) + end - start + 1 <= self.limit:
                            self._watches.append((identity, start, end))
                        else:
                            ranges[-1]["error"] = "source_gap_tracking_exhausted"
                    output.append(record)
                    if self.policy.mode == "strict" and len(output) > self.limit:
                        raise ConsumerRecoveryRequired("source_gap_exceeds_replay_limit")
                    self.cursors[identity] = current
                return replace(batch, records=tuple(output),
                               continuity=True if self.policy.mode == "strict" else batch.continuity,
                               resync_required=False if self.policy.mode == "strict" else batch.resync_required,
                               dropped_before=0 if self.policy.mode == "strict" else batch.dropped_before,
                               detail={**batch.detail, "continuity_replayed": replayed,
                                       "source_continuity": {"state": "gapped" if self._watches or ranges and self.policy.mode == "gap_aware" else "continuous",
                                                             "guarantee": "monotonic_id", "ranges": ranges}})
        except ConsumerRecoveryRequired as error:
            self._terminal = error
            await self.close()
            raise
        except asyncio.CancelledError:
            await self.close()
            raise

    async def close(self):
        await self.inner.close()
        self.service._notify_continuity()
        if self._reading is not None:
            self._reading.cancel()
            await asyncio.gather(self._reading, return_exceptions=True)
            self._reading = None

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        try:
            while (batch := await self.receive()) is not None:
                yield batch
        finally:
            await self.close()
