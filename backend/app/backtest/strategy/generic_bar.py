"""Source-independent sequential SDK adapter, preserving the V1 transcript."""
import time
from app.core.config import getenv
from .protocol import StrategyProviderError
from .python_runner import PythonRunnerError


def build_generic_bar(provider, session, adapter, market, feature_names):
    from app.backtest.colocated import _GuardedProvider
    from .python_provider import PythonHostProvider
    from .local_python import LocalPythonRunner
    if (getenv("BACKTEST_GENERIC_BAR_ENABLED", "1").strip() != "1"
            or type(provider) is not _GuardedProvider or type(provider.provider) is not PythonHostProvider
            or type(provider.provider.runner) is not LocalPythonRunner
            or not provider.provider.runner._direct_objects
            or tuple(feature_names) != ("open", "high", "low", "close", "volume")):
        return None
    from .direct_observation import _BOUNDS_COMPATIBLE
    if not _BOUNDS_COMPATIBLE:
        return None
    try:
        from . import _native_rows
    except ImportError:
        return None
    if getattr(_native_rows, "ROW_PROTOCOL_ABI", None) != 1:
        return None
    RowFactory = _native_rows.RowFactory
    from candlescope_backtest_sdk import models
    for kind, slots in ((models.Bar, ("open_time_ms", "close_time_ms", "open", "high", "low", "close", "volume")),
                        (models.Observation, ("run_id", "revision_id", "generation", "sequence", "event_time_ms",
                         "watermark_ms", "phase", "market", "bar", "features", "account_view", "input_hash"))):
        if (getattr(kind, "__slots__", None) != slots or getattr(kind, "__post_init__", None) is not None
                or getattr(getattr(kind.__init__, "__code__", None), "co_filename", None) != "<string>"):
            return None
    try:
        factory = RowFactory(session.run_id, market, models.Bar, models.Observation)
    except ValueError:
        return None
    return GenericBarAdapter(provider, session, adapter, market, factory)


class GenericBarAdapter:
    def __init__(self, guarded, session, adapter, market, factory):
        from candlescope_backtest_sdk import models
        self.models = models
        self.guarded, self.session, self.adapter = guarded, session, adapter
        self.runner = guarded.provider.runner
        self.market, self.factory = market, factory
        self.factory.bind_transcript(self.runner._transcript_hash)
        from .direct_observation import bind_native_outputs
        self.direct_outputs = (getenv("BACKTEST_NATIVE_OUTPUT_FIELDS_ENABLED", "1").strip() == "1"
                               and bind_native_outputs(factory))
        self.native_entry = (getenv("BACKTEST_NATIVE_ENTRY_ENABLED", "1").strip() == "1"
                             and self.direct_outputs
                             and self.runner._fused_output and self.runner._host_hotpath
                             and hasattr(factory, "execute"))

    def observe(self, event, phase):
        models = self.models
        prepared = None
        deadline = time.monotonic() + min(self.guarded.step_timeout, self.guarded.call_timeout)
        self.guarded.deadline.value = deadline
        try:
            signature = (models.Bar, models.Observation, models.Bar.__init__, models.Observation.__init__, models._decimal_string,
                         models.Bar.__new__, models.Observation.__new__)
            if signature == self.runner._native_sdk_signature and self.runner._count < 9007199254740991:
                if self.native_entry and hasattr(self.factory, "execute"):
                    completed = self.factory.execute(event.payload, event.sequence, event.event_time_ms,
                                                     phase, self.runner, self.session, self.direct_outputs)
                    if completed is not None:
                        if time.monotonic() > deadline:
                            raise StrategyProviderError("PROVIDER_TIMEOUT", "provider step exceeded budget")
                        return completed[0]
                else:
                    prepared = self.factory.build(event.payload, event.sequence, event.event_time_ms, phase)
            if prepared is not None:
                self.session._accept_clock(self.session.run_id, event.sequence, event.event_time_ms, event.event_time_ms)
                output = self.runner.observe_prepared(prepared, warmup=phase == "WARMUP", factory=self.factory)
                if time.monotonic() > deadline:
                    raise StrategyProviderError("PROVIDER_TIMEOUT", "provider step exceeded budget")
                return output
        except PythonRunnerError as exc:
            raise StrategyProviderError(exc.code, str(exc)) from exc
        finally:
            self.guarded.deadline.value = 0.0
        # Noncanonical numbers, unusual mappings/strings and SDK alterations
        # retain original normalization, validation and error timing.
        bar = dict(event.payload)
        features = {name: str(bar[name]) for name in ("open", "high", "low", "close", "volume")
                    if bar.get(name) is not None}
        return self.adapter.observe(sequence=event.sequence, event_time_ms=event.event_time_ms,
            watermark_ms=event.event_time_ms, phase=phase, market=self.market, bar=bar, features=features)
