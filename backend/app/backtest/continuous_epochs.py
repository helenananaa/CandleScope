"""Pre-staged financial projections and durable source bindings for repair.

Old projections and the original creation definition are never rewritten when
the active epoch changes. Expensive row/checkpoint staging precedes the source
fence; activation is a separate constant-size compare-and-swap operation.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import time
from uuid import uuid4

from .continuous_source_identity import new_source_owner


@dataclass(frozen=True)
class Projection:
    heads: str
    items: str
    active_index: str
    key: str


def create_schema(db):
    db.execute("""CREATE TABLE continuous_epochs (
        id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
        request_key TEXT NOT NULL UNIQUE, source_owner TEXT NOT NULL UNIQUE,
        initial_snapshot_json TEXT, base_identity_json TEXT NOT NULL, plan_json TEXT NOT NULL,
        phase TEXT NOT NULL, target_revision INTEGER NOT NULL,
        source_json TEXT, progress_json TEXT, error_json TEXT, updated_at_ms INTEGER NOT NULL,
        UNIQUE(run_id,id))""")
    db.execute("""CREATE TABLE active_continuous_epochs (
        run_id TEXT PRIMARY KEY REFERENCES runs(id), epoch_id TEXT NOT NULL UNIQUE,
        FOREIGN KEY(run_id,epoch_id) REFERENCES continuous_epochs(run_id,id))""")
    db.execute("""CREATE TABLE epoch_result_heads (
        run_id TEXT PRIMARY KEY REFERENCES continuous_epochs(id) ON DELETE CASCADE,
        checkpoint_revision INTEGER NOT NULL, head_json TEXT NOT NULL,
        counts_json TEXT NOT NULL, stored_bytes INTEGER NOT NULL)""")
    db.execute("""CREATE TABLE epoch_result_items (
        run_id TEXT NOT NULL REFERENCES continuous_epochs(id) ON DELETE CASCADE,
        kind TEXT NOT NULL,item_index INTEGER NOT NULL,changed_revision INTEGER NOT NULL,
        wire TEXT NOT NULL,stored_bytes INTEGER NOT NULL,active INTEGER NOT NULL,
        PRIMARY KEY(run_id,kind,item_index))""")
    db.execute("CREATE INDEX idx_epoch_result_changes ON epoch_result_items(run_id,changed_revision,kind,item_index)")
    db.execute("CREATE INDEX idx_epoch_result_active_orders ON epoch_result_items(run_id,item_index) WHERE kind='orders' AND active=1")


class ContinuousEpochs:
    def __init__(self,store):self.store=store

    def projection(self,run_id):
        row=self.store.db.execute("SELECT epoch_id FROM active_continuous_epochs WHERE run_id=?",(run_id,)).fetchone()
        if row is None:return Projection("result_heads","result_items","idx_result_active_orders",run_id)
        return Projection("epoch_result_heads","epoch_result_items","idx_epoch_result_active_orders",row[0])

    def definition(self,run_id,wire):
        definition=json.loads(wire)
        row=self.store.db.execute("SELECT e.source_owner,e.initial_snapshot_json FROM continuous_epochs e "
            "JOIN active_continuous_epochs a ON a.epoch_id=e.id WHERE a.run_id=?",(run_id,)).fetchone()
        if row is not None:
            definition["source_owner"]=row["source_owner"]
            if row["initial_snapshot_json"] is None:definition.pop("initial_snapshot",None)
            else:definition["initial_snapshot"]=json.loads(row["initial_snapshot_json"])
        return definition

    def input_references(self):
        """Keep original and adopted/staged epoch inputs, not only today's view."""
        result=[]
        for row in self.store.db.execute("SELECT definition_json FROM runs"):
            initial=json.loads(row[0]).get("initial_snapshot")
            if initial:result.append(initial)
        for row in self.store.db.execute("SELECT initial_snapshot_json FROM continuous_epochs WHERE initial_snapshot_json IS NOT NULL"):
            result.append(json.loads(row[0]))
        return result

    def stored_bytes(self):
        # Head accounting already includes every indexed row in that projection.
        rows=self.store.db.execute("SELECT COALESCE(SUM(stored_bytes),0) FROM epoch_result_heads").fetchone()[0]
        # Reserve the bounded metadata/error allowance before accepting a job.
        return rows+self.store.db.execute("SELECT count(*) FROM continuous_epochs").fetchone()[0]*65536

    @staticmethod
    def _describe(row):
        from .continuous_store import fail
        if row is None:raise fail("CONTINUOUS_REPAIR_NOT_FOUND","Unknown history repair request")
        value=dict(row)
        for field in ("initial_snapshot","base_identity","plan","source","progress","error"):
            wire=value.pop(field+"_json")
            value[field]=None if wire is None else json.loads(wire)
        return value

    def describe(self,epoch_id):
        with self.store.lock:
            if self.store.closed:
                from .continuous_store import fail
                raise fail("CONTINUOUS_STORE_CLOSED","Continuous strategy store is closed")
            return self._describe(self.store.db.execute("SELECT * FROM continuous_epochs WHERE id=?",(epoch_id,)).fetchone())

    def request(self,request_key):
        with self.store.lock:
            if self.store.closed:
                from .continuous_store import fail
                raise fail("CONTINUOUS_STORE_CLOSED","Continuous strategy store is closed")
            row=self.store.db.execute("SELECT * FROM continuous_epochs WHERE request_key=?",(request_key,)).fetchone()
            return None if row is None else self._describe(row)

    def checkpoint(self,run_id,revision):
        """Decode one explicitly chosen retained checkpoint, never all history."""
        from .continuous_store import _counter,fail
        from .continuous_source_identity import source_owner
        from app.data_engine.storage.prefix_watches import PrefixReceipt
        _counter(revision)
        with self.store.lock:
            current=self.store.summary(run_id)
            row=self.store.db.execute("SELECT * FROM checkpoints WHERE run_id=? AND revision=?",(run_id,revision)).fetchone()
            if (row is None or row["data_revision"]!=current["data_revision"] or row["revision"]>current["checkpoint_revision"]
                    or row["sequence"]>current["sequence"] or row["event_time_ms"]>current["event_time_ms"]):
                raise fail("CONTINUOUS_CHECKPOINT_UNAVAILABLE","Retained repair anchor does not belong to the active source epoch")
            definition=self.store.describe(run_id)["definition"]
            value=json.loads(row["wire"])
            if not isinstance(value,dict) or not all(isinstance(value.get(name),dict) for name in ("engine","provider","planner","source")):
                raise fail("FIDELITY_UNSUPPORTED","Repair anchor requires its qualified source/account/provider checkpoint")
            point=PrefixReceipt.from_dict(value["source"])
            if (point.owner!=source_owner(run_id,definition) or point.incarnation!=row["data_revision"]
                    or point.through_ms!=row["event_time_ms"] or point.series!=tuple(definition.get("source_series",()))):
                raise fail("CONTINUOUS_CHECKPOINT_CORRUPT","Repair anchor source and financial metadata differ")
            return {"run":current,"definition":definition,"checkpoint":value,
                "point":{key:row[key] for key in ("revision","generation","sequence","event_time_ms","data_revision")}}

    def reserve(self,run_id,request_key,*,expected,plan):
        """Private admission after user confirmation; never opens a source."""
        from .continuous_contracts import CommittedIdentity
        from .continuous_store import _text,_wire,_counter,fail
        _text(run_id,128);_text(request_key,128)
        expected=CommittedIdentity.model_validate(expected).model_dump()
        if expected["id"]!=run_id:raise fail("CONTINUOUS_INPUT_INVALID","Repair account identity differs")
        if not isinstance(plan,dict) or type(plan.get("resume_after")) is not bool:
            raise fail("CONTINUOUS_INPUT_INVALID","Confirmed repair must include its resume intent")
        base=_wire(expected,2048);plan_wire=_wire(plan,16384)
        with self.store._transaction():
            prior=self.store.db.execute("SELECT * FROM continuous_epochs WHERE request_key=?",(request_key,)).fetchone()
            if prior is not None:
                if (prior["run_id"],prior["base_identity_json"],prior["plan_json"])!=(run_id,base,plan_wire):
                    raise fail("CONTINUOUS_COMMIT_CONFLICT","Repair request key owns a different confirmed plan")
                return self._describe(prior)
            row=self.store.summary(run_id)
            if self.store.results.identity(row)!=expected or row["phase"]!="REPAIR_REQUIRED":
                raise fail("CONTINUOUS_COMMIT_CONFLICT","Observed repair-required account changed")
            definition=self.store.describe(run_id)["definition"]
            if definition.get("source_kind")!="MARKET_BAR":
                raise fail("FIDELITY_UNSUPPORTED","Repair requires its owned market source contract")
            if self.store.db.execute("SELECT 1 FROM continuous_epochs WHERE run_id=? AND phase IN ('REQUESTED','PREPARING','READY')",(run_id,)).fetchone():
                raise fail("CONTINUOUS_NOT_READY","This account already has an accepted repair")
            total,owned=self.store.db.execute("SELECT count(*),COALESCE(SUM(run_id=?),0) FROM continuous_epochs",(run_id,)).fetchone()
            if total>=64 or owned>=8:raise fail("BUDGET_EXCEEDED","Retained history repair capacity reached")
            latest=self.store.db.execute("SELECT MAX(revision) FROM checkpoints WHERE run_id=?",(run_id,)).fetchone()[0]
            target=max(row["revision"],latest)+1;_counter(target)
            epoch_id=uuid4().hex
            initial=definition.get("initial_snapshot")
            self.store.db.execute("INSERT INTO continuous_epochs(id,run_id,request_key,source_owner,initial_snapshot_json,"
                "base_identity_json,plan_json,phase,target_revision,updated_at_ms) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (epoch_id,run_id,request_key,new_source_owner(run_id),None if initial is None else _wire(initial,16384),
                 base,plan_wire,"REQUESTED",target,int(time.time()*1000)))
            self.store._enforce_total_budget()
            return self._describe(self.store.db.execute("SELECT * FROM continuous_epochs WHERE id=?",(epoch_id,)).fetchone())

    def prepare(self,epoch_id,*,source=None,initial_snapshot=None,progress=None):
        """Bounded job metadata, separate from either published account."""
        from .continuous_store import _wire,fail
        from .continuous_source_identity import source_owner
        from app.data_engine.storage.prefix_watches import PrefixReceipt
        with self.store._transaction():
            saved=self.describe(epoch_id)
            if saved["phase"] not in {"REQUESTED","PREPARING"}:
                raise fail("CONTINUOUS_COMMIT_CONFLICT","Repair preparation is no longer active")
            fields={"phase":"PREPARING","updated_at_ms":int(time.time()*1000)}
            if source is not None:
                point=PrefixReceipt.from_dict(source)
                if point.owner!=source_owner(saved["run_id"],{"source_owner":saved["source_owner"]}):
                    raise fail("CONTINUOUS_INPUT_INVALID","Repair source belongs to another account")
                fields["source_json"]=_wire(point.to_dict(),8192)
            if initial_snapshot is not None:fields["initial_snapshot_json"]=_wire(initial_snapshot,16384)
            if progress is not None:fields["progress_json"]=_wire(progress,2048)
            self.store.db.execute("UPDATE continuous_epochs SET "+",".join(name+"=?" for name in fields)+" WHERE id=?",(*fields.values(),epoch_id))
            self.store._enforce_total_budget()
        return self.describe(epoch_id)

    def fail(self,epoch_id,*,code,message,cancelled=False):
        from .continuous_store import _wire,fail
        if type(cancelled) is not bool:raise fail("CONTINUOUS_INPUT_INVALID","Repair cancellation must be explicit")
        with self.store._transaction():
            saved=self.describe(epoch_id)
            if saved["phase"]=="COMMITTED":raise fail("CONTINUOUS_COMMIT_CONFLICT","Published repair cannot be discarded")
            self.store.db.execute("UPDATE continuous_epochs SET phase=?,error_json=?,updated_at_ms=? WHERE id=?",
                ("CANCELLED" if cancelled else "FAILED",_wire({"code":str(code)[:64],"message":str(message)[:256]},4096),int(time.time()*1000),epoch_id))
        return self.describe(epoch_id)
