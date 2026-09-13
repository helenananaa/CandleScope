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
        snapshotter = lambda: provider.snapshot(compact=True)
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


def checkpoint_json(payload, session_json):
    return _object_json(payload, "provider", session_json)
