"""Read a selected research program without restoring its account or executing it."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .errors import BacktestError
from .strategy.protocol import StrategyProviderError, canonical_hash
from .strategy.python_bundle import inspect_directory

SCHEMA = "candlescope.research-selected-version/1"
MAX_SOURCE_BYTES = 2 * 1024 * 1024


def _mismatch(message):
    return BacktestError("DATA_SNAPSHOT_MISMATCH", message)


def selected_run_version(repository, run_id):
    record = repository.get_run_strategy_reference(run_id)
    if record is None:
        raise BacktestError("SCHEMA_UNKNOWN_FIELD", "Selected research run does not exist")
    if record["state"] != "COMPLETED":
        raise BacktestError("FIDELITY_UNSUPPORTED", "Select a completed research run")
    revision = repository.get_strategy_revision(record["strategy_revision_id"])
    if revision is None:
        raise _mismatch("Selected research strategy version is unavailable")
    if revision["language"] not in {"PINE_ENGINE", "PYTHON_SOURCE"}:
        raise BacktestError("FIDELITY_UNSUPPORTED", "This strategy language cannot be returned to an editor")
    try:
        config = json.loads(record["config_json"])
        compiled = json.loads(revision["compiled_json"])
        parameters = json.loads(revision["parameter_schema_json"])
        if not isinstance(config, dict) or config.get("strategy_revision_id") != revision["revision_id"]:
            raise _mismatch("Research run and strategy version do not match")
        if canonical_hash(compiled) != revision["compiled_hash"]:
            raise _mismatch("Frozen strategy compilation identity changed")
        if config.get("strategy_source") != compiled.get("executionSource", revision["source_text"]):
            raise _mismatch("Research run does not reference this frozen program")
        source = revision["source_text"]
        if canonical_hash({"language": revision["language"], "source": source}) != revision["source_hash"]:
            raise _mismatch("Frozen strategy source identity changed")
        libraries = {}
        bundle_hash = None
        if revision["language"] == "PINE_ENGINE":
            execution = json.loads(compiled["executionSource"])
            if execution["source"] != source:
                raise _mismatch("Frozen Pine source does not match its compilation")
            libraries = execution.get("libraries", {})
            if not isinstance(libraries, dict):
                raise _mismatch("Frozen Pine library identity is invalid")
            language = "pine"
        elif revision["language"] == "PYTHON_SOURCE":
            identity = json.loads(source)
            bundle = repository.get_strategy_bundle(identity["bundle_id"])
            if bundle is None or bundle["bundle_hash"] != identity["bundle_hash"]:
                raise _mismatch("Frozen Python bundle is unavailable")
            inspected = inspect_directory(Path(bundle["store_path"]))
            if inspected["bundle_hash"] != identity["bundle_hash"]:
                raise _mismatch("Frozen Python bundle content changed")
            files = inspected["files"]
            marker = json.loads(files.get("candlescope-editor.json", b"null"))
            if (marker != {"schemaVersion": "candlescope.python-editor/1"}
                    or set(files) != {"strategy.json", "strategy.py", "requirements.lock", "candlescope-editor.json"}):
                raise BacktestError("FIDELITY_UNSUPPORTED", "Select a single-file Python editor version")
            source = files["strategy.py"].decode("utf-8")
            bundle_hash = inspected["bundle_hash"]
            language = "python"
        else:
            # Never relabel a legacy runtime, external bundle or builtin as editor code.
            raise BacktestError("FIDELITY_UNSUPPORTED", "This strategy version cannot be returned to an editor")
        if not source.strip() or len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise BacktestError("FIDELITY_UNSUPPORTED", "Selected source exceeds the chart editor budget")
        if not isinstance(parameters, list) or not isinstance(config.get("parameters", {}), dict):
            raise _mismatch("Frozen strategy parameters are invalid")
        value = {
            "schema": SCHEMA, "run_id": record["run_id"], "config_hash": record["config_hash"],
            "strategy_revision_id": revision["revision_id"],
            "program": {"language": language, "name": revision["name"], "source_text": source,
                        "source_hash": "sha256:" + hashlib.sha256(source.encode("utf-8")).hexdigest(),
                        "revision_source_hash": revision["source_hash"], "compiled_hash": revision["compiled_hash"],
                        "parameter_schema": parameters, "libraries": libraries, "bundle_hash": bundle_hash},
            "configuration": config,
        }
        return {**value, "version_hash": canonical_hash(value)}
    except BacktestError:
        raise
    except (ValueError, TypeError, KeyError, OSError, StrategyProviderError) as exc:
        raise _mismatch("Selected frozen strategy version could not be read") from exc
