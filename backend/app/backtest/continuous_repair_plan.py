"""Read-only repair preview from one financial point and its source watch.

The preview never opens a strategy provider, creates a watch, copies BARs or
accepts a job. Its fingerprint includes the complete observed source version;
workers must recheck it before forking a prefix or preparing a replacement.
"""
from __future__ import annotations

import hashlib
import json

from app.data_engine.storage.prefix_watches import PrefixReceipt
from .continuous_contracts import CommittedIdentity
from .continuous_source_identity import source_owner
from .continuous_store import MAX_RETAINED_CHECKPOINTS, fail

STEP = 60_000


def preview(store, manager, run_id, *, expected, resume_after, now_ms):
    expected = CommittedIdentity.model_validate(expected).model_dump()
    if expected["id"] != run_id or type(resume_after) is not bool:
        raise fail("CONTINUOUS_INPUT_INVALID", "Repair preview requires its account and explicit resume intent")
    if type(now_ms) is not int or not 0 <= now_ms <= 9_007_199_254_740_991:
        raise fail("CONTINUOUS_INPUT_INVALID", "Repair preview requires a revealed UTC boundary")
    # Source and financial databases cannot share a transaction. Capture the
    # financial point first and bind both observations in the confirmed plan.
    with store.lock:
        if store.closed:
            raise fail("CONTINUOUS_STORE_CLOSED", "Continuous strategy store is closed")
        store.db.execute("BEGIN")
        try:
            current = store.summary(run_id)
            if store.results.identity(current) != expected or current["phase"] != "REPAIR_REQUIRED":
                raise fail("CONTINUOUS_COMMIT_CONFLICT", "Observed repair-required account changed")
            definition = store.describe(run_id)["definition"]
            if definition.get("source_kind") != "MARKET_BAR":
                raise fail("FIDELITY_UNSUPPORTED", "Repair requires the owned market BAR source")
            # Extract just one source receipt. Do not decode historical engine,
            # order, fill or provider snapshots while displaying a preview.
            row = store.db.execute("SELECT json_extract(wire,'$.source') FROM checkpoints "
                "WHERE run_id=? AND revision=?", (run_id, current["checkpoint_revision"])).fetchone()
            point = PrefixReceipt.from_dict(None if row is None or row[0] is None else json.loads(row[0]))
            if (point.owner != source_owner(run_id, definition) or point.incarnation != current["data_revision"]
                    or point.series != tuple(definition.get("source_series", ()))
                    or point.through_ms != current["event_time_ms"]):
                raise fail("CONTINUOUS_CHECKPOINT_CORRUPT", "Repair source differs from the committed account")
            candidates = [dict(row) for row in store.db.execute(
                "SELECT revision,sequence,event_time_ms,data_revision FROM checkpoints WHERE run_id=? "
                "AND data_revision=? AND revision<=? AND sequence<=? AND event_time_ms<=? "
                "ORDER BY event_time_ms DESC,revision DESC LIMIT ?",
                (run_id, current["data_revision"], current["checkpoint_revision"], current["sequence"],
                 current["event_time_ms"], MAX_RETAINED_CHECKPOINTS))]
        finally:
            store.db.execute("ROLLBACK")
    through = (now_ms // STEP) * STEP - 1
    if through < max(point.through_ms, point.from_ms):
        raise fail("LOOKAHEAD_VIOLATION", "Repair cutoff must cover the committed closed BARs")
    observed = manager.bars.prefixes.inspect(point.owner)
    matching = (observed is not None and observed["incarnation"] == point.incarnation
        and observed["from_ms"] == point.from_ms and observed["through_ms"] >= point.through_ms
        and observed["acquisition"] >= point.acquisition and observed["version"] >= point.version
        and observed["storage_revision"] >= point.storage_revision
        and tuple(observed[name] for name in ("exchange", "market_type", "symbol", "interval", "provider_id",
            "venue", "asset_class", "series_variant", "price_adjustment", "session_variant", "volume_semantics")) == point.series)
    dirty_from = observed["dirty_from_ms"] if matching else None
    dirty_through = observed["dirty_through_ms"] if matching else None
    anchor = None
    reason = "SOURCE_CONTINUITY_UNAVAILABLE"
    if matching and dirty_from is not None and dirty_through is not None:
        frozen = definition.get("initial_snapshot") or {}
        if dirty_from <= frozen.get("through_ms", point.from_ms - 1):
            # A retained private snapshot cannot silently feed old initialization
            # BARs into a repaired suffix. Re-freeze from the original start.
            reason = "INITIAL_SNAPSHOT_REVISED"
        else:
            anchor = next((row for row in candidates if row["sequence"] > 0 and row["event_time_ms"] < dirty_from), None)
            reason = None if anchor else "NO_RETAINED_CHECKPOINT_BEFORE_REVISION"
    elif matching:
        reason = "SOURCE_REVISION_NOT_LOCATABLE"
    plan = {"schema": "candlescope.continuous-repair-plan/1", "expected": expected,
        "resume_after": resume_after, "through_ms": through, "source": point.to_dict(),
        "observed_source": None if observed is None else {name: observed[name] for name in (
            "incarnation", "from_ms", "through_ms", "acquisition", "version", "storage_revision", "dirty_from_ms", "dirty_through_ms")},
        "dirty_from_ms": dirty_from, "dirty_through_ms": dirty_through,
        "anchor_revision": None if anchor is None else anchor["revision"],
        "anchor_sequence": 0 if anchor is None else anchor["sequence"],
        "from_ms": point.from_ms if anchor is None else anchor["event_time_ms"] + 1,
        "full_reinitialization": anchor is None, "expanded_range_reason": reason}
    wire = json.dumps(plan, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return {**plan, "plan_id": hashlib.sha256(wire.encode()).hexdigest()}
