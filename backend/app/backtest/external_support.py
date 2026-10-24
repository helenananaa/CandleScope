"""Negotiate new Pine evaluators while retaining known legacy adapter profiles."""
REPLAY_CONTRACT = "candlescope.external-replay/1"
PINE_LEGACY = frozenset(f"pine-external/{version}" for version in range(1, 9))
PINE_REPLAY_LEGACY = frozenset(f"pine-external/{version}" for version in range(5, 9))
PYNE_LEGACY = frozenset(f"pyne-external/{version}" for version in range(1, 6))


def negotiated_pine_replay(identity):
    adapter = identity.get("adapter")
    return (isinstance(adapter, str) and adapter.startswith("pine-external/")
            and identity.get("external_replay") == REPLAY_CONTRACT
            and identity.get("prefix_append") in {"candlescope.pine-prefix/1","candlescope.pine-prefix/2"}
            and type(identity.get("external_orders")) is int and identity["external_orders"] in {1, 2})


def external_available(language, identity):
    adapter = identity.get("adapter")
    if language == "pine":
        return adapter in PINE_LEGACY or negotiated_pine_replay(identity)
    return language == "pyne" and adapter in PYNE_LEGACY


def pine_replay_available(identity):
    return identity.get("adapter") in PINE_REPLAY_LEGACY or negotiated_pine_replay(identity)


def persistent_evaluator(identity):
    return pine_replay_available(identity) or identity.get("adapter") in {"pyne-external/4", "pyne-external/5"}
