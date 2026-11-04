"""One committed closed-BAR strategy session, without a second financial engine.

Private execution host; Runtime/DataManager source and UI integration follow this
boundary. Source coverage and repair authorization remain the source owner's job.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
import threading
import logging
import inspect

from app.market_dataset.snapshot import MarketEvent
from app.data_engine.storage.prefix_watches import PrefixReceipt, PrefixAcquisitionChanged
from app.data_engine.storage.revisions import StaleAcquisition
from .continuous_store import ContinuousStrategyStore
from .errors import BacktestError
from .models import ENGINE_VERSION
from .service import _build_bar_kernel, _new_host_planner, _planning_context, _strategy_execution_reporter, _strategy_observation_features, _assert_strategy_frame_inputs, _declared_feature_names
from .strategy.host_adapter import StrategyHostAdapter
from .strategy.protocol import StrategyProvider, StrategyProviderSession

ProviderFactory = Callable[[Mapping[str, object]], StrategyProvider]
MAX_BATCH_EVENTS = 1000
logger = logging.getLogger(__name__)


class ContinuousExecutionStopping(Exception):
    """Owned shutdown discards only uncommitted work; it is not a run failure."""


def error(code, message):
    return BacktestError(code, message)


class ContinuousBarHost:
    def __init__(self, run_id, definition, provider_factory: ProviderFactory, *, step_timeout_s=2):
        if (not isinstance(definition, Mapping) or definition.get("engine_version") != ENGINE_VERSION
                or any(not isinstance(definition.get(key), Mapping) for key in ("configuration", "input_plan", "market"))):
            raise error("CONTINUOUS_INPUT_INVALID", "A fixed engine, configuration, input plan and market are required")
        language = str(definition.get("language") or "builtin").lower()
        if language == "pyne":
            raise error("FIDELITY_UNSUPPORTED","Pyne is retired and cannot run as a continuous strategy")
        if language not in {"builtin","python","external"}:
            raise error("FIDELITY_UNSUPPORTED","This strategy language requires its own qualified execution clock")
        initial_snapshot = definition.get("initial_snapshot")
        if initial_snapshot is not None and (not isinstance(initial_snapshot,Mapping) or type(initial_snapshot.get("through_ms")) is not int):
            raise error("CONTINUOUS_INPUT_INVALID","Initial snapshot requires a fixed source boundary")
        config = definition["configuration"]
        if (any(config.get(key) for key in ("pine_runtime_identity", "pine_bar_path_contract", "pine_process_on_close"))
                or config.get("account_model") == "LINEAR_PERP_ONE_WAY_V2"
                or str(config.get("funding_mode") or "OFF") != "OFF"):
            raise error("FIDELITY_UNSUPPORTED", "This continuation host requires its qualified closed-BAR clock and account data")
        self.lock = threading.RLock()
        self.stop_requested = threading.Event()
        self.input_control = None
        self.store = None
        self.row = None
        self.source_receipt = None
        self.closed = False
        self.resources_closed = False
        self.definition = definition
        self.config = config
        provider = provider_factory(definition)
        self.session = StrategyProviderSession(provider, run_id=run_id)
        self.adapter = StrategyHostAdapter(self.session, step_timeout_s=step_timeout_s)
        try:
            capabilities = provider.describe()
            if "BAR_CLOSE" not in capabilities.input_modes or not capabilities.snapshot_restore:
                raise error("FIDELITY_UNSUPPORTED", "A resumable BAR_CLOSE provider is required")
            self.adapter.start(dict(definition["input_plan"]))
            self.feature_names = _declared_feature_names(provider) or ()
            self.input_modes = tuple(provider.describe().input_modes)
            _assert_strategy_frame_inputs(provider,bar={},trade=None,_modes=self.input_modes)
            reporter = _strategy_execution_reporter(self.session)
            self.kernel = _build_bar_kernel(config, reporter)
            if self.kernel.funding_rate != 0:
                raise error("FIDELITY_UNSUPPORTED", "This continuation requires funding OFF")
            self.planner = _new_host_planner(config, execution_reporter=reporter)
            self.planner.bind_kernel(self.kernel)
        except BaseException:
            self._close_after_failure()
            raise

    @staticmethod
    def _source_point(run_id,definition,receipt,event_time_ms,data_revision):
        if receipt is None:
            if definition.get("source_kind") == "MARKET_BAR":
                raise error("CONTINUOUS_SOURCE_UNAVAILABLE","Market input requires a durable DataManager prefix receipt")
            return None
        point = PrefixReceipt.from_dict(receipt.to_dict() if isinstance(receipt,PrefixReceipt) else dict(receipt))
        if (point.owner != "strategy:"+run_id or tuple(definition.get("source_series",())) != point.series
                or point.through_ms != event_time_ms or point.incarnation != data_revision):
            raise error("CONTINUOUS_INPUT_INVALID","The source prefix does not belong to this run, market and committed cursor")
        return point

    def checkpoint(self,source_receipt=None):
        point = self.source_receipt if source_receipt is None else source_receipt
        return {"engine":self.kernel.snapshot(), "provider":self.session.snapshot(), "planner":self.planner.snapshot(),
                **({"source":point.to_dict()} if point is not None else {})}

    @classmethod
    def create_run(cls, store, run_id, *, definition, mode, data_revision, event_time_ms, provider_factory,
                   source_receipt=None, commit_checkpoint=None):
        point = cls._source_point(run_id,definition,source_receipt,event_time_ms,data_revision)
        existing = store.find_created(run_id, definition=definition, mode=mode, data_revision=data_revision, event_time_ms=event_time_ms)
        if existing is not None:
            return existing
        host = cls(run_id, definition, provider_factory)
        host.source_receipt = point
        try:
            prepared = store.prepare_checkpoint(host.checkpoint(),event_time_ms=event_time_ms,data_revision=data_revision)
            owner_thread = threading.get_ident()
            allowed, published = True, False
            def publish():
                nonlocal published
                if not allowed or published or threading.get_ident() != owner_thread:
                    raise error("CONTINUOUS_COMMIT_CONFLICT","Creation must be synchronous and owned exactly once")
                result = store.create(run_id, definition=definition, mode=mode, data_revision=data_revision,
                                      event_time_ms=event_time_ms, checkpoint=prepared)
                published = True
                return result
            try:
                if commit_checkpoint is not None and inspect.iscoroutinefunction(commit_checkpoint):
                    raise error("CONTINUOUS_INPUT_INVALID","Source creation guard must complete synchronously")
                result = publish() if commit_checkpoint is None else commit_checkpoint(publish)
                if inspect.isawaitable(result):
                    if inspect.iscoroutine(result):result.close()
                    raise error("CONTINUOUS_INPUT_INVALID","Source creation guard must complete synchronously")
                if not published:
                    raise error("CONTINUOUS_INPUT_INVALID","Source guard did not commit creation")
                return result
            finally:
                allowed = False
        finally:
            host.close()

    @classmethod
    def resume(cls, store: ContinuousStrategyStore, run_id, provider_factory: ProviderFactory, *, retry_failed=False):
        saved = store.load(run_id)
        if saved["run"]["phase"] not in {"PAUSED","CATCHING_UP","LIVE"} and not (retry_failed is True and saved["run"]["phase"] == "FAILED"):
            raise error("CONTINUOUS_NOT_READY","Repair or failure requires explicit resolution")
        host = cls(run_id, saved["definition"], provider_factory)
        try:
            state = saved["checkpoint"]
            host.kernel.restore(state["engine"])
            host.session.restore(state["provider"])
            host.planner.restore(state["planner"])
            row = saved["run"]
            host.source_receipt = cls._source_point(run_id,saved["definition"],state.get("source"),row["event_time_ms"],row["data_revision"])
            host.row = store.resume(run_id, generation=row["generation"], revision=row["revision"],retry_failed=retry_failed)
            host.session.generation = host.row["generation"]
            host.store = store
            return host
        except BaseException:
            host._close_after_failure()
            raise

    def _observe(self, visible, event):
        self._check_stopping()
        output = self.adapter.observe(sequence=event.sequence, event_time_ms=event.event_time_ms,
            watermark_ms=event.event_time_ms,
            phase="WARMUP" if event.sequence <= int(self.config.get("warmup_bars") or 0) else "EVALUATION",
            market=dict(self.definition["market"]), bar=dict(event.payload),
            features=_strategy_observation_features(self.session.provider,bar=event.payload,trade=None,_names=self.feature_names))
        self._check_stopping()
        return self.planner.plan(output, context=None if self.planner.config is None else _planning_context(self.kernel,event))

    def request_stop(self):
        # Signal without waiting for the batch lock or touching a live provider.
        self.stop_requested.set()

    def _check_stopping(self):
        if self.stop_requested.is_set():
            raise ContinuousExecutionStopping()
        if self.input_control is not None:
            self.input_control()

    def apply_batch(self, events: Iterable[MarketEvent], *, data_revision, revealed_through_ms, coverage_complete, caught_up=False, source_receipt=None, commit_checkpoint=None):
        with self.lock:
            self._check_stopping()
            if self.closed or self.store is None or self.row is None:
                raise error("CONTINUOUS_NOT_READY", "The execution host is not active")
            current = self.store.summary(self.row["id"])
            if (current["generation"],current["revision"]) != (self.row["generation"],self.row["revision"]):
                self.close()
                raise error("CONTINUOUS_COMMIT_CONFLICT", "A newer execution owns this run")
            if data_revision != self.row["data_revision"]:
                self._stop("REPAIR_REQUIRED", "HISTORY_REVISED", "Processed input changed; await authorized repair")
                raise error("CONTINUOUS_REPAIR_REQUIRED", "Processed input changed; committed result retained")
            if type(revealed_through_ms) is not int or revealed_through_ms < self.row["event_time_ms"]:
                raise error("LOOKAHEAD_VIOLATION", "Invalid revealed source boundary")
            if coverage_complete is not True:
                self._defer("CONTINUOUS_SOURCE_GAP","Source coverage is incomplete; committed result retained")
                raise error("CONTINUOUS_SOURCE_GAP","Wait for the source owner to complete the missing range")
            if type(caught_up) is not bool:
                raise error("CONTINUOUS_INPUT_INVALID","Caught-up proof must be explicit")
            # Bound only this new batch. Never materialize/re-evaluate the full
            # historical input or finalize working orders at a chunk boundary.
            batch = []
            sequence, stamp = self.row["sequence"], self.row["event_time_ms"]
            for event in events:
                if len(batch) >= MAX_BATCH_EVENTS:
                    raise error("BUDGET_EXCEEDED", "Continuous source batch exceeds its ceiling")
                close = event.payload.get("close_time_ms")
                if (event.role != "BARS" or type(close) is not int or event.payload.get("is_closed") is False
                        or close > event.event_time_ms or event.event_time_ms > revealed_through_ms):
                    raise error("LOOKAHEAD_VIOLATION", "Only revealed closed BAR inputs may enter this execution")
                if event.sequence != sequence + 1 or event.event_time_ms < stamp:
                    self._defer("CONTINUOUS_SOURCE_GAP", "Source coverage is incomplete; committed result retained")
                    raise error("CONTINUOUS_SOURCE_GAP", "Source coverage is incomplete")
                sequence, stamp = event.sequence, event.event_time_ms
                batch.append(event)
            if not batch and (not caught_up or self.row["phase"] == "LIVE"):
                return self.row
            if caught_up and stamp != revealed_through_ms:
                raise error("CONTINUOUS_INPUT_INVALID","Caught-up publication requires the final admitted source boundary")
            point = self._source_point(self.row["id"],self.definition,source_receipt,stamp,data_revision)
            if self.source_receipt is not None:
                if (point is None or commit_checkpoint is None or point.incarnation != self.source_receipt.incarnation
                        or point.from_ms != self.source_receipt.from_ms or point.acquisition <= self.source_receipt.acquisition):
                    raise error("CONTINUOUS_SOURCE_UNAVAILABLE","A new source acquisition and guarded checkpoint commit are required")
            elif point is not None or commit_checkpoint is not None:
                raise error("CONTINUOUS_INPUT_INVALID","An unprotected run cannot acquire a different source implicitly")
            if commit_checkpoint is not None and inspect.iscoroutinefunction(commit_checkpoint):
                raise error("CONTINUOUS_INPUT_INVALID","The source commit guard must complete synchronously")
            try:
                self.kernel.advance(batch, self._observe)
                self._check_stopping()
                prepared = self.store.prepare_checkpoint(self.checkpoint(point),event_time_ms=stamp,data_revision=data_revision)
                published = False
                publication_allowed = True
                owner_thread = threading.get_ident()
                def publish():
                    nonlocal published
                    if not publication_allowed or published or self.closed or threading.get_ident() != owner_thread:
                        raise error("CONTINUOUS_COMMIT_CONFLICT","Checkpoint publication must be synchronous and owned exactly once")
                    self._check_stopping()
                    self.row = self.store.commit(self.row["id"], generation=self.row["generation"], revision=self.row["revision"],
                        sequence=sequence, event_time_ms=stamp, data_revision=data_revision, checkpoint=prepared,
                        phase="LIVE" if caught_up else "CATCHING_UP",confirm_caught_up=not batch)
                    published = True
                    return self.row
                # Prepare/encode provider state before taking the source lock.
                # The DataManager callback holds only the final source fence and
                # financial SQLite commit, never provider execution or I/O fetch.
                try:
                    result = publish() if commit_checkpoint is None else commit_checkpoint(publish)
                    if inspect.isawaitable(result):
                        if inspect.iscoroutine(result):result.close()
                        raise error("CONTINUOUS_INPUT_INVALID","Source commit cannot acknowledge asynchronous work")
                    if not published:
                        raise error("CONTINUOUS_INPUT_INVALID","Source guard did not commit its financial checkpoint")
                finally:
                    publication_allowed = False
                self.source_receipt = point
                return self.row
            except BaseException as failure:
                self.fail_input(failure)
                raise

    def fail_input(self, failure):
        """Record a source acquisition failure before execution as well as in it."""
        with self.lock:
            if self.closed:
                return
            try:
                if isinstance(failure,ContinuousExecutionStopping):
                    pass  # Keep the last committed phase/account for restart.
                elif isinstance(failure,PrefixAcquisitionChanged):
                    old = self.source_receipt
                    frozen = self.definition.get("initial_snapshot") or {}
                    protected = max(old.through_ms,int(frozen.get("through_ms",old.through_ms))) if old is not None else -1
                    if (old is not None and protected >= old.from_ms and failure.start_ms is not None and failure.end_ms is not None
                            and failure.start_ms <= protected and failure.end_ms >= old.from_ms):
                        self._stop("REPAIR_REQUIRED","CONTINUOUS_HISTORY_REVISED","Processed input changed; committed result retained")
                    else:
                        self._defer("CONTINUOUS_SOURCE_RECHECK","New input changed during acquisition; retry from committed state")
                elif isinstance(failure,StaleAcquisition):
                    self._defer("CONTINUOUS_SOURCE_RECHECK",str(failure)[:1000])
                elif getattr(failure,"code",None) in {"CONTINUOUS_SOURCE_GAP","dataset_source_gap"}:
                    self._defer("CONTINUOUS_SOURCE_GAP",str(failure))
                elif not isinstance(failure,BacktestError) or failure.code != "CONTINUOUS_COMMIT_CONFLICT":
                    self._stop("FAILED",getattr(failure,"code","CONTINUOUS_EXECUTION_FAILED"),str(failure)[:1000])
            except BaseException:
                logger.exception("Could not record continuing strategy failure; committed recovery point retained")
            self._close_after_failure()

    def _defer(self, code, message):
        try:
            self.row = self.store.defer(self.row["id"],generation=self.row["generation"],revision=self.row["revision"],
                                        reason={"code":str(code)[:64],"message":str(message)[:256]})
        except BaseException:
            self._close_after_failure()
            raise
        self.close()

    def _stop(self, phase, code, message):
        try:
            self.row = self.store.stop(self.row["id"], generation=self.row["generation"], revision=self.row["revision"],
                                       phase=phase, error={"code":str(code)[:64],"message":str(message)[:256]})
        except BaseException:
            self._close_after_failure()
            raise
        self.close()

    def pause(self):
        with self.lock:
            if self.closed:
                raise error("CONTINUOUS_NOT_READY", "The execution host is not active")
            try:
                self.row = self.store.stop(self.row["id"], generation=self.row["generation"], revision=self.row["revision"])
            except BaseException:
                self._close_after_failure()
                raise
            self.close()
            return self.row

    def _close_after_failure(self):
        try:
            self.close()
        except BaseException:
            logger.exception("Failed to close continuing strategy resources after execution failure")

    def close(self):
        self.request_stop()
        with self.lock:
            if not self.resources_closed:
                self.closed = True
                try:
                    self.adapter.close()
                finally:
                    try:
                        self.session.close()
                    except BaseException:
                        abort = getattr(self.session.provider,"abort",None)
                        if callable(abort):
                            abort()
                        raise
                self.resources_closed = True
