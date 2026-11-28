"""Reconstruct supported providers from a continuing run's own code/parameters.

No StrategyRevision, fixed dataset, smoke record or provider process is created
by preparation. Financial/input validation and atomic run creation belong to
the controller. Existing fixed-history smoke and revision rules still apply.
"""
from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from .errors import BacktestError
from .strategy.python_bundle import editor_bundle_files, freeze_bundle, inspect_files
from .strategy.python_provider import PythonHostProvider
from .strategy.registry import build_default_strategy_registry

SCHEMA = "candlescope.continuous-provider/1"
MAX_SOURCE_BYTES = 262_144
MAX_PARAMETERS_BYTES = 65_536
FIELDS = {"schema", "language", "builtin_id", "source_text", "parameters", "output_mode",
          "runtime_mode", "trusted_confirmed", "libraries", "pine",
          "strategy_revision_id", "external_connection_id", "external"}
# Only a stored definition carries the Host's Pine compilation or external binding;
# editor input never does.
STORED_FIELDS = {"pine", "external"}
EXTERNAL_FIELDS = {"strategy_revision_id", "external_connection_id", "external"}
EXTERNAL_BINDING = {"external_scope_hash", "external_provider_identity"}


def _invalid(message):
    raise BacktestError("CONTINUOUS_INPUT_INVALID", message)


def _json(value):
    pending = [(value, 0)]
    visited = 0
    while pending:
        item, depth = pending.pop()
        visited += 1
        if depth > 64 or visited > 10_000:
            _invalid("Provider configuration exceeds its structure budget")
        if isinstance(item, dict):
            if len(item)+visited > 10_000:
                _invalid("Provider configuration exceeds its structure budget")
            if any(type(key) is not str for key in item):
                _invalid("Provider configuration keys must be text")
            pending.extend((child, depth+1) for child in item.values())
        elif isinstance(item, list):
            if len(item)+visited > 10_000:
                _invalid("Provider configuration exceeds its structure budget")
            pending.extend((child, depth+1) for child in item)
        elif item is not None and type(item) not in {str, int, float, bool}:
            _invalid("Provider configuration must contain JSON values")
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError) as failure:
        raise BacktestError("CONTINUOUS_INPUT_INVALID", "Provider configuration must be finite JSON") from failure


def prepare_provider(payload):
    """Own bounded current editor code; run no strategy or filesystem operation.

    Pine code is analyzed by the installed Pine runtime (its compiler, not the script).
    """
    return _prepare_provider(payload)[0]


def _prepare_provider(payload, *, stored=False):
    if not isinstance(payload, Mapping) or set(payload)-FIELDS or (not stored and set(payload) & STORED_FIELDS):
        _invalid("Unknown continuous provider fields")
    if payload.get("schema", SCHEMA) != SCHEMA:
        _invalid("Unsupported continuous provider schema")
    language = payload.get("language")
    if language == "pyne":
        raise BacktestError("FIDELITY_UNSUPPORTED", "Pyne is retired")
    if type(language) is not str or language not in {"builtin", "python", "pine", "external"}:
        raise BacktestError("FIDELITY_UNSUPPORTED", "This language requires its own qualified continuous provider")
    if language != "pine" and ("libraries" in payload or "pine" in payload):
        _invalid("Libraries and a Pine compilation require Pine code")
    if language != "external" and set(payload) & EXTERNAL_FIELDS:
        _invalid("An external revision and connection require an external model")
    parameters = payload.get("parameters", {})
    if not isinstance(parameters, dict):
        _invalid("Provider parameters must be an object")
    raw_parameters = _json(parameters)
    if len(raw_parameters.encode("utf-8")) > MAX_PARAMETERS_BYTES:
        raise BacktestError("BUDGET_EXCEEDED", "Provider parameters exceed the storage budget")
    source = payload.get("source_text", "")
    if type(source) is not str:
        _invalid("Provider source must be text")
    try:
        source_size = len(source.encode("utf-8"))
    except UnicodeEncodeError as failure:
        raise BacktestError("CONTINUOUS_INPUT_INVALID", "Provider source must be UTF-8 text") from failure
    if source_size > MAX_SOURCE_BYTES:
        raise BacktestError("BUDGET_EXCEEDED", "Provider source exceeds the editor budget")
    mode = payload.get("output_mode", "TARGET_POSITION")
    if type(mode) is not str or mode not in {"SIGNAL", "TARGET_POSITION", "ORDER_INTENT"}:
        _invalid("Unsupported provider output mode")
    prepared = {"schema": SCHEMA, "language": language, "parameters": json.loads(raw_parameters),
                "source_text": source, "output_mode": mode}
    inspected = None
    if language == "builtin":
        if "runtime_mode" in payload or "trusted_confirmed" in payload:
            _invalid("Python runtime fields require Python editor code")
        identity = payload.get("builtin_id")
        if type(identity) is not str or not 1 <= len(identity) <= 128:
            _invalid("A supported builtin identity is required")
        # Registry also contains Pine. It must never be relabeled as a builtin.
        from .strategy.builtin import build_builtin_provider
        probe = build_builtin_provider(identity)
        try:
            descriptor = build_default_strategy_registry().require(identity)
            if source and not descriptor.accepts_source:
                _invalid("This builtin does not accept editor source")
            if mode not in probe.describe().output_modes:
                _invalid("This builtin does not support the requested output mode")
        finally:
            probe.close()
        prepared["builtin_id"] = identity
    elif language == "external":
        prepared.update(_prepare_external(payload, source, stored=stored))
    elif language == "pine":
        if any(name in payload for name in ("builtin_id", "runtime_mode", "trusted_confirmed")):
            _invalid("Pine code names no builtin or Python runtime")
        from .continuous_pine import prepare_pine
        prepared.update(prepare_pine(payload, source, mode, stored=stored))
    else:
        if "builtin_id" in payload:
            _invalid("Python editor code cannot name a builtin")
        runtime = payload.get("runtime_mode")
        confirmed = payload.get("trusted_confirmed", False)
        if type(runtime) is not str or runtime not in {"SANDBOXED_LOCAL", "TRUSTED_LOCAL"} or type(confirmed) is not bool:
            _invalid("Select a Python runtime and boolean confirmation")
        if runtime == "TRUSTED_LOCAL" and not confirmed:
            _invalid("Trusted Python requires explicit operator confirmation")
        if runtime == "SANDBOXED_LOCAL" and confirmed:
            _invalid("Trusted confirmation does not apply to the sandbox runtime")
        # Same AST/author-contract diagnostics as fixed-history editor bundles.
        inspected = inspect_files(editor_bundle_files("Continuous strategy", source))
        prepared.update(runtime_mode=runtime, trusted_confirmed=confirmed)
    return prepared, inspected


def _prepare_external(payload, source, *, stored):
    """An external model (B-333c): a registered revision's manifest, answered over its connection.

    Creation binds the connection (``ContinuousProviderFactory.bind_external``); a stored
    definition holds that binding, and every Host start checks it again.
    """
    if any(name in payload for name in ("builtin_id", "runtime_mode", "trusted_confirmed")) or source:
        _invalid("An external model runs outside the Host: it names no source, builtin or Python runtime")
    prepared = {}
    for name in ("strategy_revision_id", "external_connection_id"):
        value = payload.get(name)
        if type(value) is not str or not 1 <= len(value) <= 128 or value != value.strip():
            _invalid("An external model names its revision and forward connection")
        prepared[name] = value
    if stored:
        binding = payload.get("external")
        if not isinstance(binding, Mapping) or set(binding) != EXTERNAL_BINDING:
            _invalid("Stored external model requires its connection binding")
        prepared["external"] = json.loads(_json(dict(binding)))
    return prepared


class _OwnedEditorProvider(PythonHostProvider):
    def __init__(self, prepared, inspected, *, scratch_root=None):
        self._scratch = TemporaryDirectory(prefix="candlescope-continuous-", dir=scratch_root)
        try:
            bundle = freeze_bundle(inspected, Path(self._scratch.name)/"bundle")
            super().__init__(bundle, parameters=prepared["parameters"], mode=prepared["runtime_mode"],
                trusted_confirmed=prepared["trusted_confirmed"], editor_authorized=True,
                bound_transcript=True)
        except BaseException:
            self._scratch.cleanup()
            raise

    def close(self):
        result = super().close()
        # Keep files if physical provider shutdown raises; caller can retry.
        self._scratch.cleanup()
        return result

    def abort(self):
        super().abort()
        self._scratch.cleanup()


class ContinuousProviderFactory:
    """Use only a persisted run definition, never a mutable editor or registry row.

    The Runtime bounds live provider count. The controller owns scratch_root
    and must drain its Runtime before removing that disposable process input.
    """
    def __init__(self, *, scratch_root=None, external=None):
        self.scratch_root = scratch_root
        # The Host's ExternalProviderControl; without it no external model runs (B-333c).
        self.external = external

    def _external(self):
        if self.external is None:
            raise BacktestError("FIDELITY_UNSUPPORTED", "External models need this Host's external connections")
        self.external.require_enabled()
        return self.external

    def bind_external(self, provider, configuration, *, warmup_bars):
        """Bind a new forward run to its connected forward connection; the client must be connected."""
        from .strategy.protocol import StrategyProviderError
        try:
            control = self._external()
            manifest = control.manifest(provider["strategy_revision_id"])
            if provider["output_mode"] not in manifest.output_modes:
                raise BacktestError("FIDELITY_UNSUPPORTED", "The external model does not decide in this output mode")
            if warmup_bars < manifest.warmup_bars:
                raise BacktestError("CONTINUOUS_INPUT_INVALID",
                    f"The external model needs at least {manifest.warmup_bars} warmup bars")
            binding = control.forward_binding(provider["strategy_revision_id"], provider["external_connection_id"],
                                              configuration)
        except StrategyProviderError as failure:
            raise BacktestError(failure.code, str(failure)) from failure
        return {key: binding[key] for key in EXTERNAL_BINDING}

    def __call__(self, definition):
        if not isinstance(definition, Mapping):
            _invalid("A continuing run definition is required")
        prepared, inspected = _prepare_provider(definition.get("provider"), stored=True)
        if _json(prepared) != _json(definition["provider"]):
            _invalid("Stored provider requires its complete prepared identity")
        execution_inputs(definition)
        if prepared["language"] == "builtin":
            from .strategy.builtin import build_builtin_provider
            return build_builtin_provider(prepared["builtin_id"])
        if prepared["language"] == "pine":
            from .strategy.pine_engine import PineEngineProvider
            return PineEngineProvider()
        if prepared["language"] == "external":
            from .strategy.protocol import StrategyProviderError
            binding = {"strategy_revision_id": prepared["strategy_revision_id"],
                       "external_connection_id": prepared["external_connection_id"], **prepared["external"]}
            try:
                return self._external().build_forward_provider(binding, definition["configuration"])
            except StrategyProviderError as failure:
                raise BacktestError(failure.code, str(failure)) from failure
        return _OwnedEditorProvider(prepared, inspected, scratch_root=self.scratch_root)


def execution_inputs(definition):
    """Derive transient Host input from the one persisted source/parameter owner.

    Called after factory validation by the Host. Optional old inline fields
    must agree; creation can omit them rather than store three source copies.
    """
    prepared = definition["provider"]
    config, plan = definition.get("configuration"), definition.get("input_plan")
    if (definition.get("language") != prepared["language"]
            or not isinstance(config, Mapping) or not isinstance(plan, Mapping)
            or plan.get("roles") != ["BARS"]):
        _invalid("Stored provider and execution language/input clock must agree")
    config, plan = dict(config), dict(plan)
    # A Pine provider prepares from the Host's compiled envelope, as a fixed-history run does.
    pine = prepared.get("pine")
    source = pine["execution_source"] if prepared["language"] == "pine" else prepared["source_text"]
    for name, plan_name, expected in (("parameters", "parameters", prepared["parameters"]),
            ("output_mode", "outputMode", prepared["output_mode"]),
            ("strategy_source", "source", source)):
        if ((name in config and _json(config[name]) != _json(expected))
                or (plan_name in plan and _json(plan[plan_name]) != _json(expected))):
            _invalid("Stored provider and execution parameters/source must agree")
        config[name] = plan[plan_name] = expected
    if prepared["language"] == "pine":
        from .continuous_pine import pine_input_plan
        if config.get("pine_runtime_identity") != pine["dependency_hash"]:
            _invalid("Stored Pine provider and execution identity must agree")
        plan.update(pine_input_plan(config))
    return config, plan
