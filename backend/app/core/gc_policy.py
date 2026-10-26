"""Keep CPython's full (generation-2) collections short.

A full collection walks every tracked container the process keeps alive while
holding the GIL, so its pause grows with the live heap rather than with the
garbage it finds.  On a running backend almost all of that heap is long-lived:

* the startup heap: modules, classes, FastAPI routes, pydantic schemas and the
  services built by ``startup_event``.  It lives until shutdown, so it is moved
  into CPython's permanent generation once startup completes (``gc.freeze``).
* parsed exchange catalogs: CCXT ``load_markets()`` tables that long-lived
  clients load after startup (a Binance spot table alone is ~1.8M references).
  They are plain dict/list/tuple trees without reference cycles, so reference
  counting alone frees them.  They are removed from cycle detection once
  loaded (``untrack_acyclic_tree``) instead of being frozen, because a frozen
  client that is later closed would pin its whole table forever.

Neither step strands cyclic garbage: the freeze collects first and is undone
at shutdown, and untracking only applies to plain containers of acyclic data.
"""
from __future__ import annotations

import asyncio
import ctypes
import gc
import logging
import sys
import time
from typing import Any

logger = logging.getLogger(__name__)

_PLAIN_CONTAINERS = (dict, list, tuple)
# Containers plus items visited between event-loop yields while untracking.
_UNTRACK_BATCH_ITEMS = 20_000


def _bind_untrack() -> Any:
    if sys.implementation.name != "cpython":
        return None
    try:
        prototype = ctypes.PYFUNCTYPE(None, ctypes.py_object)
        return prototype(("PyObject_GC_UnTrack", ctypes.pythonapi))
    except (AttributeError, OSError):
        return None


_untrack = _bind_untrack()
_state: dict[str, Any] = {
    "startup_freeze": None,
    "untracked_containers": 0,
    "untrack_calls": 0,
}


def freeze_startup_heap(*, enabled: bool = True) -> dict[str, Any] | None:
    """Collect once, then exclude everything alive now from later collections.

    Call at the end of application startup, before the server accepts
    requests: the one full collection here replaces the first full pass that
    would otherwise run while serving.
    """

    if not enabled:
        return None
    started = time.perf_counter()
    collected = gc.collect()
    collect_ms = (time.perf_counter() - started) * 1000.0
    gc.freeze()
    result = {
        "collect_ms": round(collect_ms, 1),
        "collected": collected,
        "frozen_objects": gc.get_freeze_count(),
    }
    _state["startup_freeze"] = result
    logger.info("Froze startup heap out of full GC passes: %s", result)
    return result


def unfreeze_startup_heap() -> None:
    """Return frozen objects to the collector, e.g. after application shutdown."""

    if _state["startup_freeze"] is None:
        return
    gc.unfreeze()
    _state["startup_freeze"] = None


async def untrack_acyclic_tree(*roots: object) -> int:
    """Exclude plain dict/list/tuple trees from cyclic garbage collection.

    Only for data that cannot form reference cycles (parsed JSON and tables
    derived from it); reference counting still frees it.  Other objects inside
    the tree stay tracked and are not descended into.  A dict that later gains
    a container is re-tracked by CPython itself.  The walk yields to the event
    loop between batches, so the tree must not be mutated while it runs.
    """

    if _untrack is None:
        return 0
    stack = [root for root in roots if type(root) in _PLAIN_CONTAINERS and gc.is_tracked(root)]
    untracked = 0
    budget = _UNTRACK_BATCH_ITEMS
    while stack:
        node = stack.pop()
        # Shared subtrees are reached more than once; an untracked node has
        # already been handled (or holds no containers).
        if not gc.is_tracked(node):
            continue
        _untrack(node)
        untracked += 1
        for child in node.values() if type(node) is dict else node:
            if type(child) in _PLAIN_CONTAINERS and gc.is_tracked(child):
                stack.append(child)
        budget -= len(node) + 1
        if budget <= 0:
            budget = _UNTRACK_BATCH_ITEMS
            await asyncio.sleep(0)
    _state["untracked_containers"] += untracked
    _state["untrack_calls"] += 1
    return untracked


def gc_policy_snapshot() -> dict[str, Any]:
    return {
        "frozen_objects": gc.get_freeze_count(),
        "startup_freeze": _state["startup_freeze"],
        "untrack_supported": _untrack is not None,
        "untracked_containers": _state["untracked_containers"],
        "untrack_calls": _state["untrack_calls"],
        "counts": gc.get_count(),
        "thresholds": gc.get_threshold(),
    }
