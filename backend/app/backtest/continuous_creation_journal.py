"""Bounded creation intent in the same transaction domain as financial state.

The controller owns workers, source copies and prefix fences. This journal owns
the first cutoff and idempotency, and fences stale preparation before publication.
"""
from __future__ import annotations

from dataclasses import replace
from collections.abc import Mapping
import json
import uuid

from app.data_engine.storage.prefix_watches import PrefixReceipt
from .continuous_store import _text, _counter, _wire, fail, MAX_DEFINITION_BYTES

STEP = 60_000
MAX_INPUT_METADATA = 32_768
SUMMARY = "request_key,run_id,mode,from_ms,cutoff_ms,dataset_id,revision,phase,error_json"


def create_schema(db):
    db.execute("""CREATE TABLE creation_requests (
        request_key TEXT PRIMARY KEY,run_id TEXT NOT NULL UNIQUE,mode TEXT NOT NULL,
        from_ms INTEGER NOT NULL,cutoff_ms INTEGER NOT NULL,dataset_id TEXT,
        definition_json TEXT,revision INTEGER NOT NULL,phase TEXT NOT NULL,
        watch_json TEXT,input_json TEXT,error_json TEXT)""")


def _summary(row):
    if row is None:raise fail("CONTINUOUS_CREATION_NOT_FOUND","Unknown continuing creation request")
    result={name:row[name] for name in SUMMARY.split(",")}
    result["error"]=json.loads(result.pop("error_json") or "null")
    return result


class ContinuousCreationJournal:
    def __init__(self,store):self.store=store

    def _row(self,key):
        if self.store.closed:raise fail("CONTINUOUS_STORE_CLOSED","Continuous strategy store is closed")
        return self.store.db.execute("SELECT * FROM creation_requests WHERE request_key=?",(key,)).fetchone()

    def _definition(self,row):
        if row["definition_json"] is not None:return json.loads(row["definition_json"])
        value=self.store.db.execute("SELECT definition_json FROM runs WHERE id=?",(row["run_id"],)).fetchone()
        if value is None:raise fail("CONTINUOUS_CHECKPOINT_CORRUPT","Committed creation lost its run definition")
        definition=json.loads(value[0]);definition.pop("initial_snapshot",None)
        return definition

    def _describe(self,row):
        return {**_summary(row),"definition":self._definition(row),
            "watch":json.loads(row["watch_json"] or "null"),"input":json.loads(row["input_json"] or "null")}

    def describe(self,key):
        with self.store.lock:return self._describe(self._row(key))

    def list_pending(self):
        with self.store.lock:
            if self.store.closed:raise fail("CONTINUOUS_STORE_CLOSED","Continuous strategy store is closed")
            return [_summary(row) for row in self.store.db.execute(
                "SELECT "+SUMMARY+" FROM creation_requests WHERE phase!='COMMITTED' ORDER BY request_key")]

    def _pending_count(self,exclude=None):
        return self.store.db.execute("SELECT count(*) FROM creation_requests WHERE phase!='COMMITTED' AND request_key IS NOT ?",
                                     (exclude,)).fetchone()[0]

    def reserve(self,key,*,definition,mode,cutoff_ms,from_ms=None):
        _text(key,128);_counter(cutoff_ms)
        if type(mode) is not str or mode not in {"HISTORY_LIVE","LIVE_ONLY"} or (cutoff_ms+1)%STEP:
            raise fail("CONTINUOUS_INPUT_INVALID","Creation requires an exact closed UTC minute cutoff")
        if not isinstance(definition,Mapping) or "initial_snapshot" in definition or definition.get("source_kind")!="MARKET_BAR":
            raise fail("CONTINUOUS_INPUT_INVALID","Reserve a preflighted market definition before fixing input")
        wire=_wire(definition,MAX_DEFINITION_BYTES)
        if mode=="HISTORY_LIVE":
            _counter(from_ms)
            if from_ms < STEP or from_ms%STEP or not 1<=(cutoff_ms+1-from_ms)//STEP<=200_000:
                raise fail("CONTINUOUS_INPUT_INVALID","Creation history must be a bounded nonempty closed minute window")
        elif from_ms is not None:
            raise fail("CONTINUOUS_INPUT_INVALID","Pure live creation cannot initialize chart history")
        with self.store._transaction():
            row=self._row(key)
            if row is not None:
                if (row["mode"]!=mode or (mode=="HISTORY_LIVE" and row["from_ms"]!=from_ms)
                        or _wire(self._definition(row),MAX_DEFINITION_BYTES)!=wire):
                    raise fail("CONTINUOUS_COMMIT_CONFLICT","Creation key already owns different code or conditions")
                return self._describe(row)  # Never move the first cutoff on retry.
            if self.store.db.execute("SELECT count(*) FROM runs").fetchone()[0]+self._pending_count()>=self.store.max_runs:
                raise fail("BUDGET_EXCEEDED","Continuing creation capacity reached")
            run_id="cs_"+uuid.uuid4().hex
            dataset_id="local-"+uuid.uuid4().hex if mode=="HISTORY_LIVE" else None
            self.store.db.execute("INSERT INTO creation_requests VALUES(?,?,?,?,?,?,?,1,'REQUESTED',NULL,NULL,NULL)",
                (key,run_id,mode,from_ms if mode=="HISTORY_LIVE" else cutoff_ms+1,cutoff_ms,dataset_id,wire))
            result=self._describe(self._row(key))
        self.store.updates.notify(run_id)
        return result

    def _expected(self,key,revision):
        _counter(revision);row=self._row(key);_summary(row)
        if row["revision"]!=revision or row["phase"] in {"FAILED","COMMITTED"}:
            raise fail("CONTINUOUS_COMMIT_CONFLICT","Creation preparation changed or is no longer open")
        return row

    @staticmethod
    def _point(row,definition,value):
        point=PrefixReceipt.from_dict(value)
        if (point.owner!="strategy:"+row["run_id"] or point.series!=tuple(definition.get("source_series",()))
                or point.from_ms!=row["from_ms"]):
            raise fail("CONTINUOUS_INPUT_INVALID","Creation source receipt belongs to a different run or window")
        return point

    def register_watch(self,key,*,revision,receipt):
        raw=_wire(receipt,MAX_INPUT_METADATA)
        with self.store._transaction():
            row=self._expected(key,revision)
            if row["phase"]!="REQUESTED":raise fail("CONTINUOUS_NOT_READY","Creation already owns a source watch")
            point=self._point(row,self._definition(row),json.loads(raw))
            if point.through_ms!=row["from_ms"]-1 or point.acquisition!=0:
                raise fail("CONTINUOUS_INPUT_INVALID","Creation requires its original unprocessed source watch")
            self.store.db.execute("UPDATE creation_requests SET watch_json=?,revision=revision+1,phase=? WHERE request_key=?",
                (raw,"READY" if row["mode"]=="LIVE_ONLY" else "WATCHED",key))
            result=self._describe(self._row(key))
        self.store.updates.notify(row["run_id"])
        return result

    def freeze_input(self,key,*,revision,descriptor,proof):
        if not isinstance(descriptor,Mapping) or not isinstance(proof,Mapping):
            raise fail("CONTINUOUS_INPUT_INVALID","Frozen creation requires its descriptor and source proof")
        raw=_wire({"descriptor":descriptor,"proof":proof},MAX_INPUT_METADATA)
        with self.store._transaction():
            row=self._expected(key,revision)
            if row["phase"]!="WATCHED" or row["mode"]!="HISTORY_LIVE":
                raise fail("CONTINUOUS_NOT_READY","Only uninitialized history may publish a frozen input")
            definition=self._definition(row);point=self._point(row,definition,proof)
            original=PrefixReceipt.from_dict(json.loads(row["watch_json"]))
            if (point.incarnation!=original.incarnation or point.through_ms!=row["cutoff_ms"]
                    or point.acquisition<=original.acquisition or point.version<original.version
                    or descriptor.get("dataset_id")!=row["dataset_id"]
                    or descriptor.get("interval")!="1m" or descriptor.get("from_ms")!=row["from_ms"]
                    or descriptor.get("through_ms")!=row["cutoff_ms"] or descriptor.get("source_version")!=point.version
                    or not isinstance(descriptor.get("data_epoch"),str) or not 1<=len(descriptor["data_epoch"])<=256):
                raise fail("CONTINUOUS_INPUT_INVALID","Frozen input must preserve the reserved source window and identity")
            self.store.db.execute("UPDATE creation_requests SET input_json=?,revision=revision+1,phase='READY' WHERE request_key=?",(raw,key))
            result=self._describe(self._row(key))
        self.store.updates.notify(row["run_id"])
        return result

    def creation_context(self,key):
        with self.store.lock:
            row=self._row(key);result=self._describe(row)
            if row["phase"] not in {"READY","COMMITTED"}:
                raise fail("CONTINUOUS_NOT_READY","Creation has not fixed its input")
            proof=result["input"]["proof"] if result["input"] else result["watch"]
            point=PrefixReceipt.from_dict(proof)
            if result["input"]:result["definition"]["initial_snapshot"]=result["input"]["descriptor"]
            return {**result,"proof":point,"receipt":replace(point,through_ms=row["from_ms"]-1)}

    def fail(self,key,*,revision,code,message):
        error=_wire({"code":_text(code,64),"message":str(message)[:256]},1024)
        with self.store._transaction():
            row=self._expected(key,revision)
            self.store.db.execute("UPDATE creation_requests SET phase='FAILED',revision=revision+1,error_json=? WHERE request_key=?",(error,key))
            result=self._describe(self._row(key))
        self.store.updates.notify(row["run_id"])
        return result

    def retry_failed(self,key,*,revision,refresh_input=False):
        _counter(revision)
        if type(refresh_input) is not bool:raise fail("CONTINUOUS_INPUT_INVALID","Input refresh must be explicit")
        with self.store._transaction():
            row=self._row(key);_summary(row)
            if row["phase"]!="FAILED" or row["revision"]!=revision:
                raise fail("CONTINUOUS_COMMIT_CONFLICT","Creation failure changed or retry was not explicit")
            input_json=None if refresh_input else row["input_json"]
            phase="READY" if input_json or (row["mode"]=="LIVE_ONLY" and row["watch_json"]) else "WATCHED" if row["watch_json"] else "REQUESTED"
            self.store.db.execute("UPDATE creation_requests SET phase=?,input_json=?,revision=revision+1,error_json=NULL WHERE request_key=?",(phase,input_json,key))
            result=self._describe(self._row(key))
        self.store.updates.notify(row["run_id"])
        return result

    def guard_creation(self,claim,*,run_id,definition,mode,data_revision,event_time_ms):
        """Read under the caller's financial transaction (or initial retry read)."""
        if not isinstance(claim,tuple) or len(claim)!=2:raise fail("CONTINUOUS_INPUT_INVALID","Creation requires a key and revision")
        key,revision=claim;_text(key,128);_counter(revision)
        context=self.creation_context(key)
        if (context["phase"]!="COMMITTED" and context["revision"]!=revision) or (
                context["run_id"]!=run_id or context["mode"]!=mode or event_time_ms!=context["from_ms"]-1
                or data_revision!=context["receipt"].incarnation
                or _wire(definition,MAX_DEFINITION_BYTES)!=_wire(context["definition"],MAX_DEFINITION_BYTES)):
            raise fail("CONTINUOUS_COMMIT_CONFLICT","Stale preparation cannot publish a different continuing account")
        return key

    def _commit_creation(self,key):
        # Same SQLite transaction as the first financial checkpoint. The run
        # now owns the sole source/code definition; retain only small intent metadata.
        self.store.db.execute("UPDATE creation_requests SET phase='COMMITTED',definition_json=NULL,revision=revision+1 WHERE request_key=? AND phase='READY'",(key,))

    def list_unstarted(self):
        """Durable launch intent after create committed but before Runtime start.

        Explicit pause records a new financial revision even at initial PAUSED,
        so it cannot be mistaken for this crash window on application restart.
        """
        with self.store.lock:
            if self.store.closed:raise fail("CONTINUOUS_STORE_CLOSED","Continuous strategy store is closed")
            return [row[0] for row in self.store.db.execute("SELECT r.id FROM creation_requests c JOIN runs r ON r.id=c.run_id "
                "WHERE c.phase='COMMITTED' AND r.phase='PAUSED' AND r.generation=1 AND r.revision=1 ORDER BY r.id")]

    def initial_start_pending(self,run_id):
        return run_id in self.list_unstarted()
