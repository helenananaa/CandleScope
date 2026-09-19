"""Compose canonical checkpoint JSON from already encoded provider state.

Fragments are produced here from live objects, never accepted from a caller's
wire input. Hashes and byte ceilings retain the original canonical JSON rules.
"""
from app.core.config import getenv
from .identity import canonical_json


def checkpoint_session(session):
    from .colocated import _GuardedProvider
    from .strategy.chart_pyne import ChartPyneStrategyProvider

    provider = session.provider
    owned = provider.provider if type(provider) is _GuardedProvider else provider
    snapshotter = None
    if (type(owned) is ChartPyneStrategyProvider
            and getenv("BACKTEST_COMPACT_CHART_CHECKPOINT_ENABLED", "1").strip() == "1"):
        def snapshotter():
            return provider.snapshot(compact=True)
    snapshot, raw_json = session.snapshot_encoded(snapshotter=snapshotter)
    # The old budget uses `provider or {}`, including for unusual falsey values.
    provider_size = len(raw_json.encode("utf-8")) if snapshot["provider"] else 2
    encoded = _object_json(snapshot, "provider", raw_json)
    return snapshot, encoded, provider_size


def _object_json(value, fragment_key, fragment):
    return "{" + ",".join(
        canonical_json(key) + ":" + (fragment if key == fragment_key else canonical_json(value[key]))
        for key in sorted(value)
    ) + "}"


def checkpoint_json(payload, session_json, *, history=None):
    if history is None or not history.reuse_encoding or "historyEncoding" not in payload:
        return _object_json(payload, "provider", session_json)
    from .checkpoint_history import history_locations

    # These fragments belong to the immediately preceding owned snapshot.
    # Only known manifest fields are substituted; no wire input is executable JSON.
    owners = {}
    try:
        for owner, name in history_locations(payload):
            manifest = owner[name]
            cached = history.fragments.get(id(manifest))
            if cached is not None and cached[0] is manifest:
                owners.setdefault(id(owner), {})[name] = cached[1]
        engine = payload["engine"]
        engine_fragments = owners.get(id(engine), {})
        if payload.get("checkpointMode") == "DUAL_CLOCK":
            execution = engine["execution"]
            engine_fragments["execution"] = _object_fragments(
                execution, owners.get(id(execution), {})
            )
        return _object_fragments(payload, {
            "provider": session_json,
            "engine": _object_fragments(engine, engine_fragments),
        })
    finally:
        history.fragments.clear()


def _object_fragments(value, fragments):
    return "{" + ",".join(
        canonical_json(key) + ":" + (fragments[key] if key in fragments else canonical_json(value[key]))
        for key in sorted(value)
    ) + "}"
