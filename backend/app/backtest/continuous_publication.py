"""Prepare complete repair rows before the short source/financial CAS fence."""
from __future__ import annotations

import json
import time

from app.data_engine.storage.prefix_watches import PrefixReceipt
from .continuous_source_identity import source_owner
from .continuous_store import MAX_CHECKPOINT_BYTES,_counter,_wire,fail
from .continuous_results import KINDS,MAX_ITEM_BYTES,MAX_PAGE_BYTES,HEAD_OVERHEAD_BYTES,ENTRY_OVERHEAD_BYTES


class ContinuousRepairPublication:
    def __init__(self,store):self.store=store

    def seed(self,epoch_id,staged,*,definition,proof):
        from .continuous_repair_seed import seed_unchanged
        return seed_unchanged(self,epoch_id,staged,definition=definition,proof=proof)

    def _base(self,saved):
        row=self.store.summary(saved["run_id"])
        if row["phase"]!="REPAIR_REQUIRED" or self.store.results.identity(row)!=saved["base_identity"]:
            raise fail("CONTINUOUS_COMMIT_CONFLICT","Confirmed repair account changed before publication")
        return row

    def _staging(self,saved):
        self._base(saved)
        current=self.store.epochs.describe(saved["id"])
        if current["phase"] not in {"REQUESTED","PREPARING"} or any(current[field]!=saved[field]
                for field in ("source_owner","initial_snapshot","base_identity","target_revision")):
            raise fail("CONTINUOUS_COMMIT_CONFLICT","Repair staging intent changed")

    def _clear_partial(self,saved,check_stopping):
        """Bound each writer interval while retaining the old active view."""
        while True:
            check_stopping()
            with self.store._transaction():
                self._staging(saved)
                rows=self.store.db.execute("SELECT rowid,stored_bytes FROM epoch_result_items WHERE run_id=? LIMIT 100",(saved["id"],)).fetchall()
                if not rows:
                    self.store.db.execute("DELETE FROM epoch_result_heads WHERE run_id=?",(saved["id"],));return
                self.store.db.executemany("DELETE FROM epoch_result_items WHERE rowid=?",((row[0],) for row in rows))
                self.store.db.execute("UPDATE epoch_result_heads SET stored_bytes=stored_bytes-? WHERE run_id=?",
                    (sum(row[1] for row in rows),saved["id"]))

    def stage(self,epoch_id,staged,*,check_stopping=lambda:None):
        """Copy a finished owned account in bounded pages, without a source lock.

        The execution owner has drained the staged worker before entering this
        method. The read transaction additionally pins its SQLite checkpoint and
        normalized rows against an independent writer.
        """
        if staged is self.store or staged.path.resolve()==self.store.path.resolve():
            raise fail("CONTINUOUS_INPUT_INVALID","Repair staging requires an independent owned financial store")
        saved=self.store.epochs.describe(epoch_id)
        if saved["phase"] not in {"REQUESTED","PREPARING"}:
            raise fail("CONTINUOUS_COMMIT_CONFLICT","Repair staging is no longer active")
        with self.store.lock:self._base(saved)
        cutoff=saved["plan"].get("through_ms");_counter(cutoff)
        if (cutoff+1)%60000 or cutoff<saved["base_identity"]["event_time_ms"]:
            raise fail("CONTINUOUS_INPUT_INVALID","Repair must finish its confirmed closed input window")
        check_stopping()
        with staged.lock:
            if staged.closed:raise fail("CONTINUOUS_STORE_CLOSED","Staged account is closed")
            staged.db.execute("BEGIN")
            try:
                row=staged.summary(saved["run_id"])
                definition=staged.describe(saved["run_id"])["definition"]
                original=self.store.describe(saved["run_id"])["definition"]
                stable=lambda value:{key:item for key,item in value.items() if key not in {"source_owner","initial_snapshot"}}
                if (_wire(stable(definition),1024*1024)!=_wire(stable(original),1024*1024)
                        or definition.get("source_owner")!=saved["source_owner"]
                        or definition.get("initial_snapshot")!=saved["initial_snapshot"]
                        or row["mode"]!=self.store.summary(saved["run_id"])["mode"]
                        or row["phase"]!="LIVE" or row["event_time_ms"]!=cutoff
                        or row["data_revision"]==saved["base_identity"]["data_revision"]):
                    raise fail("CONTINUOUS_INPUT_INVALID","Staged repair changed strategy/configuration or did not finish its confirmed window")
                source_row=staged.db.execute("SELECT sequence,event_time_ms,data_revision,stored_bytes,"
                    "json_extract(CAST(wire AS TEXT),'$.source') AS source FROM checkpoints WHERE run_id=? AND revision=?",
                    (row["id"],row["checkpoint_revision"])).fetchone()
                if source_row is None or source_row["source"] is None:
                    raise fail("CONTINUOUS_CHECKPOINT_CORRUPT","Staged repair has no durable source receipt")
                point=PrefixReceipt.from_dict(json.loads(source_row["source"]))
                if ((source_row["sequence"],source_row["event_time_ms"],source_row["data_revision"])!=(row["sequence"],row["event_time_ms"],row["data_revision"])
                        or point.owner!=source_owner(row["id"],definition) or point.incarnation!=row["data_revision"]
                        or point.through_ms!=cutoff or tuple(definition["source_series"])!=point.series
                        or not 0<source_row["stored_bytes"]<=MAX_CHECKPOINT_BYTES):
                    raise fail("CONTINUOUS_CHECKPOINT_CORRUPT","Staged account/source/checkpoint identity differs")
                projection=staged.epochs.projection(row["id"])
                head=staged.db.execute(f"SELECT * FROM {projection.heads} WHERE run_id=?",(projection.key,)).fetchone()
                if head is None or head["checkpoint_revision"]!=row["checkpoint_revision"]:
                    raise fail("CONTINUOUS_RESULTS_UNAVAILABLE","Staged repair results are not complete")
                counts=json.loads(head["counts_json"])
                if set(counts)!=set(KINDS) or any(type(value) is not int or value<0 for value in counts.values()):
                    raise fail("CONTINUOUS_RESULTS_INVALID","Staged repair counts are invalid")
                initial_bytes=len(head["head_json"].encode())+len(head["counts_json"].encode())+HEAD_OVERHEAD_BYTES
                self._clear_partial(saved,check_stopping)
                with self.store._transaction():
                    self._staging(saved)
                    self.store.db.execute("INSERT INTO epoch_result_heads VALUES(?,?,?,?,?)",
                        (epoch_id,saved["target_revision"],head["head_json"],head["counts_json"],initial_bytes))
                    self.store._enforce_total_budget()
                seen={kind:0 for kind in KINDS};items=[];used=0;total=initial_bytes
                def flush():
                    nonlocal items,used
                    if not items:return
                    check_stopping()
                    with self.store._transaction():
                        self._staging(saved)
                        self.store.db.executemany("INSERT INTO epoch_result_items VALUES(?,?,?,?,?,?,?)",items)
                        self.store.db.execute("UPDATE epoch_result_heads SET stored_bytes=stored_bytes+? WHERE run_id=?",(used,epoch_id))
                        self.store._enforce_total_budget()
                    items=[];used=0
                for item in staged.db.execute(f"SELECT kind,item_index,wire,stored_bytes,active FROM {projection.items} WHERE run_id=? ORDER BY kind,item_index",(projection.key,)):
                    check_stopping()
                    kind,index,wire,size,active=tuple(item)
                    if (kind not in seen or index!=seen[kind] or index>=counts[kind]
                            or not ENTRY_OVERHEAD_BYTES<=size<=MAX_ITEM_BYTES+ENTRY_OVERHEAD_BYTES
                            or len(wire.encode())+ENTRY_OVERHEAD_BYTES!=size):
                        raise fail("CONTINUOUS_RESULTS_INVALID","Staged repair projection is incomplete or corrupt")
                    if items and (used+size>MAX_PAGE_BYTES or len(items)>=100):flush()
                    items.append((epoch_id,kind,index,saved["target_revision"],wire,size,active))
                    used+=size;total+=size;seen[kind]+=1
                flush()
                if seen!=counts or total!=head["stored_bytes"]:
                    raise fail("CONTINUOUS_RESULTS_INVALID","Staged repair result counts or byte accounting differ")
                check_stopping()
                # One bounded raw recovery wire, never decoded/copied inside the
                # source guard. It remains invisible until the active pointer CAS.
                wire=staged.db.execute("SELECT wire FROM checkpoints WHERE run_id=? AND revision=?",(row["id"],row["checkpoint_revision"])).fetchone()[0]
                if len(wire)!=source_row["stored_bytes"]:
                    raise fail("CONTINUOUS_CHECKPOINT_CORRUPT","Staged repair recovery size differs")
                check_stopping()
                with self.store._transaction():
                    self._staging(saved)
                    self.store.db.execute("INSERT INTO checkpoints VALUES(?,?,?,?,?,?,?,?)",
                        (row["id"],saved["target_revision"],saved["base_identity"]["generation"]+1,row["sequence"],cutoff,point.incarnation,wire,len(wire)))
                    self.store.db.execute("UPDATE continuous_epochs SET phase='READY',source_json=?,updated_at_ms=? WHERE id=?",
                        (_wire(point.to_dict(),8192),int(time.time()*1000),epoch_id))
                    self.store._enforce_total_budget()
            finally:staged.db.execute("ROLLBACK")
        return self.store.epochs.describe(epoch_id)

    def publish(self,epoch_id,manager,*,resume_after):
        if type(resume_after) is not bool:raise fail("CONTINUOUS_INPUT_INVALID","Repair resume intent must be explicit")
        saved=self.store.epochs.describe(epoch_id)
        if resume_after!=saved["plan"]["resume_after"]:
            raise fail("CONTINUOUS_COMMIT_CONFLICT","Repair resume intent differs from its confirmed request")
        if saved["phase"]=="COMMITTED":return self.store.summary(saved["run_id"])
        if saved["phase"]!="READY":raise fail("CONTINUOUS_NOT_READY","Repair results are not prepared for publication")
        point=PrefixReceipt.from_dict(saved["source"])
        def publish():
            with self.store._transaction():
                current=self.store.epochs.describe(epoch_id)
                if current["phase"]!="READY" or current["source"]!=saved["source"]:
                    raise fail("CONTINUOUS_COMMIT_CONFLICT","Prepared repair changed before publication")
                self._base(saved)
                checkpoint=self.store.db.execute("SELECT sequence,event_time_ms,data_revision,generation FROM checkpoints WHERE run_id=? AND revision=?",
                    (saved["run_id"],saved["target_revision"])).fetchone()
                head=self.store.db.execute("SELECT checkpoint_revision FROM epoch_result_heads WHERE run_id=?",(epoch_id,)).fetchone()
                if (checkpoint is None or head is None or head[0]!=saved["target_revision"]
                        or (checkpoint["event_time_ms"],checkpoint["data_revision"],checkpoint["generation"])!=(
                            point.through_ms,point.incarnation,saved["base_identity"]["generation"]+1)):
                    raise fail("CONTINUOUS_CHECKPOINT_CORRUPT","Prepared repair metadata is unavailable")
                self.store.db.execute("INSERT INTO active_continuous_epochs VALUES(?,?) ON CONFLICT(run_id) DO UPDATE SET epoch_id=excluded.epoch_id",
                    (saved["run_id"],epoch_id))
                self.store.db.execute("UPDATE runs SET generation=?,revision=?,phase=?,sequence=?,event_time_ms=?,data_revision=?,checkpoint_revision=?,error_json=NULL,updated_at_ms=? WHERE id=?",
                    (checkpoint["generation"],saved["target_revision"],"CATCHING_UP" if resume_after else "PAUSED",checkpoint["sequence"],point.through_ms,
                     point.incarnation,saved["target_revision"],int(time.time()*1000),saved["run_id"]))
                self.store.db.execute("UPDATE continuous_epochs SET phase='COMMITTED',updated_at_ms=? WHERE id=?",(int(time.time()*1000),epoch_id))
                self.store._enforce_total_budget()
            return self.store.summary(saved["run_id"])
        try:return manager.bars.prefixes.commit(point,publish,committed_through_ms=point.through_ms)
        except Exception:
            # A durable financial swap can precede a failed source acknowledgement.
            # The already-persisted source epoch still supports exact restoration.
            if self.store.epochs.describe(epoch_id)["phase"]=="COMMITTED":return self.store.summary(saved["run_id"])
            raise
        finally:
            self.store.updates.notify(saved["run_id"])
