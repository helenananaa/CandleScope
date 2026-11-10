"""Restore a proven unchanged financial prefix without evaluating it again."""
from __future__ import annotations

import time

from app.data_engine.storage.prefix_watches import PrefixReceipt
from .continuous_source_identity import source_owner
from .continuous_store import _wire,fail


def seed_unchanged(publication,epoch_id,staged,*,definition,proof):
    """Only a fresh private staging store may receive an anchor.

    The new source watch already exists before this work. Further amendments
    invalidate it, and both suffix acquisition and the final financial source
    fence recheck it. No source lock covers checkpoint encoding/index writes.
    """
    store=publication.store
    if staged is store or staged.path.resolve()==store.path.resolve():
        raise fail("CONTINUOUS_INPUT_INVALID","Repair seed requires an independent owned staging store")
    with staged.lock:
        if staged.closed:raise fail("CONTINUOUS_STORE_CLOSED","Repair staging store is closed")
        if staged.db.execute("SELECT 1 FROM runs LIMIT 1").fetchone() or staged.db.execute("SELECT 1 FROM continuous_epochs LIMIT 1").fetchone():
            raise fail("CONTINUOUS_COMMIT_CONFLICT","Refuse to replace an existing staging account")
    saved=store.epochs.describe(epoch_id)
    if saved["phase"] not in {"REQUESTED","PREPARING"}:
        raise fail("CONTINUOUS_COMMIT_CONFLICT","Repair seed intent is no longer active")
    revision=saved["plan"].get("anchor_revision")
    if type(revision) is not int or revision<1:
        raise fail("CONTINUOUS_INPUT_INVALID","An explicitly planned retained checkpoint is required")
    anchor=store.epochs.checkpoint(saved["run_id"],revision)
    point=PrefixReceipt.from_dict(proof.to_dict() if isinstance(proof,PrefixReceipt) else proof)
    old=PrefixReceipt.from_dict(anchor["checkpoint"]["source"])
    immutable=lambda value:{key:item for key,item in value.items() if key not in {"source_owner","initial_snapshot"}}
    if (saved["source"] is None or PrefixReceipt.from_dict(saved["source"])!=point or point.owner!=source_owner(saved["run_id"],definition)
            or point.owner!=saved["source_owner"] or point.incarnation==old.incarnation
            or (point.series,point.from_ms,point.through_ms)!=(old.series,old.from_ms,old.through_ms)
            or point.storage_revision<old.storage_revision
            or _wire(immutable(definition),1024*1024)!=_wire(immutable(anchor["definition"]),1024*1024)
            or definition.get("initial_snapshot")!=saved["initial_snapshot"]):
        raise fail("CONTINUOUS_INPUT_INVALID","Repair seed differs from its proven unchanged account/source prefix")
    with store.lock:publication._staging(saved)
    state={**anchor["checkpoint"],"source":point.to_dict()}
    prepared=staged.prepare_checkpoint(state,event_time_ms=point.through_ms,data_revision=point.incarnation,
        run_id=saved["run_id"],initial=True)
    definition_wire=_wire(definition,1024*1024)
    with staged._transaction():
        if staged.db.execute("SELECT 1 FROM runs LIMIT 1").fetchone() or staged.db.execute("SELECT 1 FROM continuous_epochs LIMIT 1").fetchone():
            raise fail("CONTINUOUS_COMMIT_CONFLICT","Refuse to replace an existing staging account")
        staged.db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (saved["run_id"],definition_wire,anchor["run"]["mode"],1,1,"PAUSED",anchor["point"]["sequence"],
             point.through_ms,point.incarnation,1,None,int(time.time()*1000)))
        staged._insert_checkpoint(saved["run_id"],1,1,anchor["point"]["sequence"],point.through_ms,point.incarnation,prepared)
        staged._enforce_total_budget()
    return staged.summary(saved["run_id"])
