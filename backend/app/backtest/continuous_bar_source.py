"""DataManager-owned closed BAR input, sealed initialization then live catchup.

Only the first qualified UTC 1m clock is admitted here. Backend runtime owns
scheduling, demand and retry/repair authorization; views never own this source.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import threading
from typing import Callable

from app.data_engine.data_manager.models import SeriesKey
from app.data_engine.storage.prefix_watches import PrefixReceipt
from app.local_data.service import LocalDatasetService
from app.market_dataset.snapshot import MarketEvent
from .errors import BacktestError
from .continuous_bar_host import ContinuousExecutionStopping

STEP = 60_000
MAX_INITIAL_BARS = 200_000
MAX_BATCH_BARS = 1000


def failure(message):
    return BacktestError("CONTINUOUS_SOURCE_GAP", message)


@dataclass(frozen=True)
class FrozenInitialInput:
    descriptor: dict
    proof: PrefixReceipt
    receipt: PrefixReceipt


@dataclass(frozen=True)
class MarketBarBatch:
    proof: PrefixReceipt
    events: tuple[MarketEvent, ...]
    revealed_through_ms: int
    caught_up: bool

    def apply(self, host, manager):
        if not self.events and host.row["phase"] == "LIVE":
            return host.row
        through = self.events[-1].event_time_ms if self.events else host.row["event_time_ms"]
        return host.apply_batch(self.events, data_revision=self.proof.incarnation,
            revealed_through_ms=self.revealed_through_ms, coverage_complete=True,
            caught_up=self.caught_up, source_receipt=replace(self.proof,through_ms=through),
            commit_checkpoint=lambda publish:manager.bars.prefixes.commit(
                self.proof,publish,committed_through_ms=through))


class ContinuousMarketBarSource:
    def __init__(self, manager, local_datasets: LocalDatasetService, key: SeriesKey, *, clock_ms: Callable[[], int], auto_backfill=False):
        if key.interval != "1m":
            raise BacktestError("FIDELITY_UNSUPPORTED","Continuous market input requires its qualified UTC 1m base clock")
        self.manager, self.local_datasets, self.key, self.clock_ms = manager, local_datasets, key, clock_ms
        self.auto_backfill = bool(auto_backfill)
        self._reader = None
        self._reader_identity = None
        self.closed = False
        self.stop_requested = threading.Event()

    def _check_stopping(self):
        if self.stop_requested.is_set():
            raise ContinuousExecutionStopping()

    def request_stop(self):
        self.stop_requested.set()

    def _boundary(self, through_ms):
        self._check_stopping()
        now = self.clock_ms()
        if (self.closed or type(now) is not int or type(through_ms) is not int
                or (through_ms + 1) % STEP or through_ms > (now // STEP)*STEP-1):
            raise BacktestError("LOOKAHEAD_VIOLATION","Input boundary must be a revealed closed UTC minute")

    def register(self, run_id, *, from_ms, definition=None):
        if self.closed or type(from_ms) is not int or from_ms % STEP:
            raise failure("Input must start at its exact UTC minute")
        from .continuous_source_identity import source_owner
        return self.manager.bars.prefixes.register(source_owner(run_id,definition or {}),self.key,
            from_ms=from_ms,committed_through_ms=from_ms-1)

    def _query_rows(self, start_ms, through_ms, revision):
        cursor = start_ms
        while cursor <= through_ms:
            self._check_stopping()
            last = min(through_ms,cursor+MAX_BATCH_BARS*STEP-1)
            count = (last+1-cursor)//STEP
            result = self.manager.bars.query(self.key.symbol,self.key.interval,
                exchange=self.key.exchange,market_type=self.key.market_type,series_identity=self.key.identity,
                start_ms=cursor,end_ms=last-STEP+1,limit=count,
                min_revision=revision,auto_backfill=self.auto_backfill,backfill_requester="continuous-strategy")
            if (not result.complete or result.retryable or result.missing_ranges or result.excluded_ranges
                    or len(result.bars) != count):
                raise failure("Wait for DataManager to complete the exact closed input window")
            for index, bar in enumerate(result.bars):
                self._check_stopping()
                opened = cursor+index*STEP
                if not bar.trusted_final or bar.time*1000 != opened:
                    raise failure("DataManager input is not contiguous trusted closed OHLCV")
                payload = {name:LocalDatasetService._decimal_text(LocalDatasetService._host_decimal(bar,name,index+1))
                    for name in ("open","high","low","close","volume")}
                yield {**payload,"open_time_ms":opened,"close_time_ms":opened+STEP-1,"is_closed":True}
            cursor = last+1

    def freeze_initial(self, receipt, *, through_ms, dataset_id, max_payload_bytes=None):
        """Prepare one immutable input; caller guards initial financial creation.

        The whole source window is protected before the first page query. The
        returned proof must fence publication after copy/provider preparation;
        any concurrent amendment invalidates it, including unprocessed suffixes.
        """
        self._boundary(through_ms)
        if receipt.through_ms != receipt.from_ms-1:
            raise failure("Initialization requires an empty financial input cursor")
        count = (through_ms+1-receipt.from_ms)//STEP
        if not 1 <= count <= MAX_INITIAL_BARS:
            raise BacktestError("BUDGET_EXCEEDED","Initial input exceeds its bounded snapshot budget")
        if max_payload_bytes is not None and (type(max_payload_bytes) is not int or max_payload_bytes<1):
            raise BacktestError("CONTINUOUS_INPUT_INVALID","Initial input byte budget must be positive")
        proof = self.manager.bars.prefixes.prepare(receipt,
            committed_through_ms=receipt.through_ms,through_ms=through_ms)
        def rows():
            used=0
            for row in self._query_rows(receipt.from_ms,through_ms,proof.storage_revision):
                used+=64+sum(len(row[name]) for name in ("open","high","low","close","volume"))
                if max_payload_bytes is not None and used>max_payload_bytes:
                    raise BacktestError("BUDGET_EXCEEDED","Initial OHLCV payload exceeds its byte budget")
                yield row
        manifest = self.local_datasets.freeze_host_bars(
            rows(),
            dataset_id=dataset_id,name="Strategy initialization",exchange=self.key.exchange,
            market_type=self.key.market_type,symbol=self.key.symbol,interval=self.key.interval,
            chart_context_hash=proof.owner)
        return FrozenInitialInput({"dataset_id":manifest["dataset_id"],"data_epoch":manifest["data_epoch"],
            "interval":self.key.interval,"from_ms":receipt.from_ms,"through_ms":through_ms,
            "source_version":proof.version},proof,replace(proof,through_ms=receipt.through_ms))

    def acquire(self, host, *, revealed_through_ms, limit=MAX_BATCH_BARS):
        self._boundary(revealed_through_ms)
        if type(limit) is not int or not 1 <= limit <= MAX_BATCH_BARS:
            raise BacktestError("BUDGET_EXCEEDED","Continuous input batch exceeds its ceiling")
        receipt = host.source_receipt
        series = (self.key.exchange,self.key.market_type,self.key.symbol,self.key.interval,*self.key.identity.storage_values)
        if receipt is None or receipt.series != series or receipt.through_ms != host.row["event_time_ms"]:
            raise failure("The source does not own this committed strategy cursor")
        cursor = receipt.through_ms+1
        frozen = host.definition.get("initial_snapshot")
        initializing = frozen is not None and cursor <= frozen["through_ms"]
        if revealed_through_ms < receipt.through_ms:
            raise BacktestError("LOOKAHEAD_VIOLATION","Revealed source boundary precedes the committed account")
        if cursor > revealed_through_ms:
            proof = self.manager.bars.prefixes.prepare(receipt,committed_through_ms=receipt.through_ms,
                through_ms=max(receipt.through_ms,frozen["through_ms"]) if initializing else receipt.through_ms,
                **({"frozen_version":frozen["source_version"]} if initializing else {}))
            return MarketBarBatch(proof,(),revealed_through_ms,True)
        last = min(revealed_through_ms,cursor+limit*STEP-1,
            frozen["through_ms"] if initializing else revealed_through_ms)
        proof = self.manager.bars.prefixes.prepare(receipt,committed_through_ms=receipt.through_ms,
            through_ms=max(last,frozen["through_ms"]) if initializing else last,
            **({"frozen_version":frozen["source_version"]} if initializing else {}))
        if initializing:
            identity = (frozen["dataset_id"],frozen["data_epoch"],frozen["interval"],frozen["from_ms"],frozen["through_ms"])
            if identity != self._reader_identity:
                if self._reader is not None:self._reader.close()
                self._reader = self.local_datasets.open_pinned_bar_window(identity[0],data_epoch=identity[1],
                    interval=identity[2],from_ms=identity[3],through_ms=identity[4])
                self._reader_identity = identity
            rows = self._reader.read_window(start_ms=cursor,limit=(last+1-cursor)//STEP)
        else:
            if self._reader is not None:
                self._reader.close();self._reader=None;self._reader_identity=None
            rows = self._query_rows(cursor,last,proof.storage_revision)
        events = tuple(MarketEvent(host.row["sequence"]+index,row["close_time_ms"],"BARS",row)
            for index,row in enumerate(rows,start=1))
        return MarketBarBatch(proof,events,revealed_through_ms,last==revealed_through_ms)

    def close(self):
        self.request_stop()
        if self._reader is not None:self._reader.close();self._reader=None
        self.closed = True
        # Prefix protection survives ordinary shutdown, pause and view close.
