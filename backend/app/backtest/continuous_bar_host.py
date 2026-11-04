"""One committed closed-BAR strategy session, without a second financial engine.

Private execution host; Runtime/DataManager source and UI integration follow this
boundary. Source coverage and repair authorization remain the source owner's job.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
import threading
import logging

from app.market_dataset.snapshot import MarketEvent
from .continuous_store import ContinuousStrategyStore
from .errors import BacktestError
from .models import ENGINE_VERSION
from .service import _build_bar_kernel, _new_host_planner, _planning_context, _strategy_execution_reporter, _strategy_observation_features, _assert_strategy_frame_inputs, _declared_feature_names
from .strategy.host_adapter import StrategyHostAdapter
from .strategy.protocol import StrategyProvider, StrategyProviderSession

ProviderFactory = Callable[[Mapping[str, object]], StrategyProvider]
MAX_BATCH_EVENTS = 1000
logger = logging.getLogger(__name__)


def error(code, message):
    return BacktestError(code, message)


class ContinuousBarHost:
    def __init__(self, run_id, definition, provider_factory: ProviderFactory, *, step_timeout_s=2):
        if (not isinstance(definition, Mapping) or definition.get("engine_version") != ENGINE_VERSION
                or any(not isinstance(definition.get(key), Mapping) for key in ("configuration", "input_plan", "market"))):
            raise error("CONTINUOUS_INPUT_INVALID", "A fixed engine, configuration, input plan and market are required")
        config = definition["configuration"]
        if (any(config.get(key) for key in ("pine_runtime_identity", "pine_bar_path_contract", "pine_process_on_close"))
                or config.get("account_model") == "LINEAR_PERP_ONE_WAY_V2"
                or str(config.get("funding_mode") or "OFF") != "OFF"):
            raise error("FIDELITY_UNSUPPORTED", "This continuation host requires its qualified closed-BAR clock and account data")
        self.lock = threading.RLock()
        self.store = None
        self.row = None
        self.closed = False
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

    def checkpoint(self):
        return {"engine":self.kernel.snapshot(), "provider":self.session.snapshot(), "planner":self.planner.snapshot()}

    @classmethod
    def create_run(cls, store, run_id, *, definition, mode, data_revision, event_time_ms, provider_factory):
        existing = store.find_created(run_id, definition=definition, mode=mode, data_revision=data_revision, event_time_ms=event_time_ms)
        if existing is not None:
            return existing
        host = cls(run_id, definition, provider_factory)
        try:
            return store.create(run_id, definition=definition, mode=mode, data_revision=data_revision,
                                event_time_ms=event_time_ms, checkpoint=host.checkpoint())
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
            host.row = store.resume(run_id, generation=row["generation"], revision=row["revision"],retry_failed=retry_failed)
            host.session.generation = host.row["generation"]
            host.store = store
            return host
        except BaseException:
            host._close_after_failure()
            raise

    def _observe(self, visible, event):
        output = self.adapter.observe(sequence=event.sequence, event_time_ms=event.event_time_ms,
            watermark_ms=event.event_time_ms,
            phase="WARMUP" if event.sequence <= int(self.config.get("warmup_bars") or 0) else "EVALUATION",
            market=dict(self.definition["market"]), bar=dict(event.payload),
            features=_strategy_observation_features(self.session.provider,bar=event.payload,trade=None,_names=self.feature_names))
        return self.planner.plan(output, context=None if self.planner.config is None else _planning_context(self.kernel,event))

    def apply_batch(self, events: Iterable[MarketEvent], *, data_revision, revealed_through_ms, coverage_complete, caught_up=False):
        with self.lock:
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
            if not batch:
                return self.row
            if caught_up and stamp != revealed_through_ms:
                raise error("CONTINUOUS_INPUT_INVALID","Caught-up publication requires the final admitted source boundary")
            try:
                self.kernel.advance(batch, self._observe)
                self.row = self.store.commit(self.row["id"], generation=self.row["generation"], revision=self.row["revision"],
                    sequence=sequence, event_time_ms=stamp, data_revision=data_revision, checkpoint=self.checkpoint(),
                    phase="LIVE" if caught_up else "CATCHING_UP")
                return self.row
            except BaseException as failure:
                # Account/provider mutations after the last committed cursor
                # cannot survive a failed commit. Close this in-memory instance;
                # a new host must load the entire committed triple before retry.
                if not isinstance(failure, BacktestError) or failure.code != "CONTINUOUS_COMMIT_CONFLICT":
                    try:
                        self._stop("FAILED", getattr(failure,"code","CONTINUOUS_EXECUTION_FAILED"), str(failure)[:1000])
                    except BaseException:
                        pass  # Preserve the original I/O/provider failure.
                self._close_after_failure()
                raise

    def _defer(self, code, message):
        try:
            self.row = self.store.defer(self.row["id"],generation=self.row["generation"],revision=self.row["revision"],
                                        reason={"code":code,"message":message})
        except BaseException:
            self._close_after_failure()
            raise
        self.close()

    def _stop(self, phase, code, message):
        try:
            self.row = self.store.stop(self.row["id"], generation=self.row["generation"], revision=self.row["revision"],
                                       phase=phase, error={"code":code,"message":message})
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
        with self.lock:
            if not self.closed:
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
