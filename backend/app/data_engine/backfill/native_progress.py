"""Small canonical receipts for Bybit native backfill tasks across quota deferrals."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from hashlib import sha256
from itertools import islice

from app.data_engine.history.calendar import AlwaysOpenCalendar
from app.data_engine.interval_policy import row_is_closed
from app.data_engine.kline_quality import source_is_trusted_final
from app.data_engine.series_identity import identity_from_metadata
from app.exchanges.rate_limits import RateLimitDeferred

from .models import BackfillTask, FetchResult, ReconcileResult, WrittenRange

# A default 1,000-row native chunk can plan one task per row.
_MAX_TASKS = 1024
_MAX_ROWS_PER_TASK = 1024
_MAX_WRITES_PER_TASK = 16
_FIELDS = (
    "open_time", "close_time", "open", "high", "low", "close", "volume",
    "quote_volume", "trades", "taker_buy_base", "taker_buy_quote", "source",
)


def _digest(rows: list[dict]) -> bytes:
    payload = sha256()
    for row in rows:
        payload.update(repr(tuple(row.get(name) for name in _FIELDS)).encode())
        payload.update(b"\n")
    return payload.digest()


async def _read_rows(storage, task: BackfillTask) -> list[dict]:
    return await storage.query_time_range(
        task.symbol, task.interval, task.start_ms, task.end_ms,
        exchange=task.exchange, market_type=task.market_type,
        series_identity=identity_from_metadata(task.exchange, task.metadata),
    )


@dataclass(frozen=True, slots=True)
class _Receipt:
    task: BackfillTask
    digest: bytes
    written: tuple[WrittenRange, ...]


@dataclass(slots=True)
class NativeBackfillProgress:
    receipts: dict[str, _Receipt] = field(default_factory=dict)

    def subset(self, start_ms: int, end_ms: int) -> NativeBackfillProgress | None:
        receipts = {key: value for key, value in self.receipts.items()
                    if start_ms <= value.task.start_ms <= value.task.end_ms <= end_ms}
        return NativeBackfillProgress(receipts) if receipts else None

    def to_ledger(self) -> list[dict]:
        return [{
            "start_ms": receipt.task.start_ms,
            "end_ms": receipt.task.end_ms,
            "digest": receipt.digest.hex(),
            "written": [[item.start_ms, item.end_ms, item.bars_written, item.source, item.phase]
                        for item in receipt.written],
        } for receipt in self.receipts.values() if len(receipt.written) <= _MAX_WRITES_PER_TASK]

    @classmethod
    def from_ledger(cls, request, payload: object) -> NativeBackfillProgress | None:
        if request.exchange != "bybit" or not isinstance(payload, list) or len(payload) > _MAX_TASKS:
            return None
        identity = identity_from_metadata(request.exchange, request.metadata)
        metadata = {"series_identity": identity.to_dict()} if identity is not None else {}
        progress = cls()
        calendar = AlwaysOpenCalendar()
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            start, end, digest = (entry.get(key) for key in ("start_ms", "end_ms", "digest"))
            if (type(start) is not int or type(end) is not int
                    or not request.start_ms <= start <= end <= request.end_ms
                    or not isinstance(digest, str) or len(digest) != 64):
                continue
            try:
                fingerprint = bytes.fromhex(digest)
                count = sum(1 for _ in islice(
                    calendar.expected_opens(start, end, request.interval), _MAX_ROWS_PER_TASK + 1,
                ))
            except ValueError:
                continue
            if len(fingerprint) != 32 or not 0 < count <= _MAX_ROWS_PER_TASK:
                continue
            task = BackfillTask(request.symbol, request.interval, start, end,
                                exchange=request.exchange, market_type=request.market_type, metadata=metadata)
            written = []
            raw_writes = entry.get("written")
            if not isinstance(raw_writes, list) or len(raw_writes) > _MAX_WRITES_PER_TASK:
                continue
            for item in raw_writes:
                if not isinstance(item, list) or len(item) != 5:
                    break
                lower, upper, count, source, phase = item
                if (not all(type(x) is int for x in (lower, upper, count))
                        or not (start <= lower <= upper <= end and 0 < count <= _MAX_ROWS_PER_TASK)
                        or not (isinstance(source, str) and source_is_trusted_final(source))
                        or phase not in ("standard", "archive_standard")):
                    break
                written.append(WrittenRange(request.symbol, request.interval, lower, upper,
                                            count, request.exchange, request.market_type, source, phase))
            if len(written) != len(raw_writes):
                continue
            progress.receipts[task.task_key] = _Receipt(task, fingerprint, tuple(written))
        return progress if progress.receipts else None

    async def verify(self, storage, *, exchange: str, market_type: str, symbol: str,
                     start_ms: int | None, end_ms: int | None, metadata: dict) -> None:
        identity = identity_from_metadata(exchange, metadata)
        for key, receipt in tuple(self.receipts.items()):
            task = receipt.task
            if ((task.exchange, task.market_type, task.symbol) != (exchange, market_type, symbol)
                    or identity_from_metadata(exchange, task.metadata) != identity
                    or (start_ms is not None and task.start_ms < start_ms)
                    or (end_ms is not None and task.end_ms > end_ms)):
                del self.receipts[key]
                continue
            rows = await _read_rows(storage, task)
            if _digest(rows) != receipt.digest:
                del self.receipts[key]

    async def remember(self, storage, fetched: list[FetchResult], reconciled: ReconcileResult) -> None:
        if reconciled.errors:
            return
        calendar = AlwaysOpenCalendar()
        for result in fetched:
            if len(self.receipts) >= _MAX_TASKS:
                return
            task = result.task
            expected = list(islice(
                calendar.expected_opens(task.start_ms, task.end_ms, task.interval),
                _MAX_ROWS_PER_TASK + 1,
            ))
            if not expected or len(expected) > _MAX_ROWS_PER_TASK:
                continue
            if expected != [bar.open_time for bar in result.bars]:
                continue
            rows = await _read_rows(storage, task)
            if not all(row_is_closed(row) and source_is_trusted_final(row.get("source")) for row in rows):
                continue
            # Grant reuse only for the inputs actually fetched by this task.
            # A competing canonical writer or a rejected row cannot mint a receipt.
            received = [{**bar.to_storage_dict(), "source": bar.source} for bar in result.bars]
            digest = _digest(rows)
            if digest != _digest(received):
                continue
            written = []
            for item in reconciled.written_ranges:
                if (item.exchange, item.market_type, item.symbol, item.interval) != (
                    task.exchange, task.market_type, task.symbol, task.interval
                ):
                    continue
                opens = [opened for opened in expected if item.start_ms <= opened <= item.end_ms]
                if opens:
                    written.append(replace(item, start_ms=opens[0], end_ms=opens[-1], bars_written=len(opens)))
            identity = identity_from_metadata(task.exchange, task.metadata)
            scope = {"series_identity": identity.to_dict()} if identity is not None else {}
            self.receipts[task.task_key] = _Receipt(
                replace(task, parent_gap=None, metadata=scope), digest, tuple(written),
            )

    def include_writes(self, result: ReconcileResult) -> None:
        for receipt in self.receipts.values():
            result.written_ranges.extend(receipt.written)
            result.bars_written += sum(item.bars_written for item in receipt.written)


class NativeBackfillDeferred(RateLimitDeferred):
    def __init__(self, deferred: RateLimitDeferred, progress: NativeBackfillProgress,
                 reconcile_result: ReconcileResult) -> None:
        super().__init__(deferred.admission)
        self.progress = progress
        self.reconcile_result = reconcile_result
