"""Current normalized results, atomically published with financial checkpoints.

The qualified kernel owns append histories. Only previously active orders and
the last equity sample can mutate. Preparing a patch reads those indices and
encodes their updates plus new tails, never revalidates/copies old history.
Readers use one SQLite snapshot and never select the recovery checkpoint wire.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json

from app.simulation.contract_accounting import ContractAccount
from app.simulation.spot_cash_account import SpotCashAccount
from app.market_dataset.snapshot import MarketDatasetError
from .errors import BacktestError

KINDS=("orders","fills","decisions","rejected","equity_curve","ledger",
    "order_events","frozen_intents","fill_source_events")
REQUIRED=("orders","fills","decisions","rejected","equity_curve")
MAX_HEAD_BYTES=32*1024
MAX_ITEM_BYTES=256*1024
MAX_PAGE_BYTES=1024*1024
MAX_PAGE_ITEMS=200
ENTRY_OVERHEAD_BYTES=256
HEAD_OVERHEAD_BYTES=1024


def error(code,message):return BacktestError(code,message)


def encode(value,limit):
    try:wire=json.dumps(value,sort_keys=True,separators=(",",":"),default=str,allow_nan=False)
    except (TypeError,ValueError,RecursionError) as failure:
        raise error("CONTINUOUS_INPUT_INVALID","Result projection requires finite JSON") from failure
    if len(wire.encode("utf-8"))>limit:raise error("BUDGET_EXCEEDED","Continuous result payload exceeds its budget")
    return wire


def valuation(account):
    """Reuse the actual account's formulas with only its scalar balance fields.

    No history restore, replay, order finalization or new persisted account.
    A sampled equity point is not the current committed account valuation.
    """
    model=account.get("account_model","LINEAR_PERP_ONE_WAY_V1")
    if type(model) is not str or model not in {"SPOT_CASH_V1","LINEAR_PERP_ONE_WAY_V1"}:
        raise error("FIDELITY_UNSUPPORTED","Continuous account valuation requires its qualified V1 model")
    try:
        values={name:None if account.get(name) is None else Decimal(str(account[name]))
            for name in ("quote_balance","position_qty","entry_price","mark")}
        values["multiplier"]=Decimal(str(account["contract_rules"]["multiplier"]))
        if (values["quote_balance"] is None or values["position_qty"] is None or values["multiplier"]<=0
                or any(value is not None and not value.is_finite() for value in values.values())):raise ValueError
        view=(SpotCashAccount if model=="SPOT_CASH_V1" else ContractAccount)(**values)
        return {"account_model":model,"equity":str(view.equity()),"unrealized_pnl":str(view.unrealized())}
    except (KeyError,TypeError,ValueError,InvalidOperation,MarketDatasetError) as failure:
        raise error("CONTINUOUS_RESULTS_INVALID","Committed account valuation is unavailable") from failure


def create_schema(db):
    db.execute("""CREATE TABLE result_heads (
        run_id TEXT PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
        checkpoint_revision INTEGER NOT NULL,head_json TEXT NOT NULL,
        counts_json TEXT NOT NULL,stored_bytes INTEGER NOT NULL)""")
    db.execute("""CREATE TABLE result_items (
        run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
        kind TEXT NOT NULL,item_index INTEGER NOT NULL,changed_revision INTEGER NOT NULL,
        wire TEXT NOT NULL,stored_bytes INTEGER NOT NULL,active INTEGER NOT NULL,
        PRIMARY KEY(run_id,kind,item_index))""")
    db.execute("CREATE INDEX idx_result_changes ON result_items(run_id,changed_revision,kind,item_index)")
    db.execute("CREATE INDEX idx_result_active_orders ON result_items(run_id,item_index) WHERE kind='orders' AND active=1")


@dataclass(frozen=True)
class ResultItem:
    kind: str
    index: int
    wire: str
    stored_bytes: int
    active: int
    old_bytes: int


@dataclass(frozen=True)
class ResultPatch:
    run_id: str
    initial: bool
    base_checkpoint_revision: int | None
    head_json: str
    counts_json: str
    stored_bytes: int
    items: tuple[ResultItem,...]


class ContinuousResults:
    def __init__(self,store):self.store=store

    def prepare(self,run_id,engine,*,initial=False):
        """Called before the short source/financial commit fence."""
        with self.store.lock:
            if self.store.closed:raise error("CONTINUOUS_STORE_CLOSED","Continuous strategy store is closed")
        if (not isinstance(engine,Mapping) or not isinstance(engine.get("account"),Mapping)
                or not {"quote_balance","position_qty","contract_rules"}<=set(engine["account"])
                or any(not isinstance(engine.get(kind),list) for kind in REQUIRED)):
            with self.store.lock:
                projection=self.store.epochs.projection(run_id)
                exists=self.store.db.execute(f"SELECT 1 FROM {projection.heads} WHERE run_id=?",(projection.key,)).fetchone()
            if exists:raise error("CONTINUOUS_RESULTS_INVALID","A qualified result cannot lose its kernel contract")
            return None  # Preserve opaque legacy recovery state; do not relabel it.
        if engine["account"].get("account_model")=="LINEAR_PERP_ONE_WAY_V2":
            raise error("FIDELITY_UNSUPPORTED","Continuous V2 accounts require their own result contract")
        arrays={kind:engine.get(kind,[]) for kind in KINDS if kind!="ledger"}
        arrays["ledger"]=engine["account"].get("journal",[])
        if any(not isinstance(value,list) for value in arrays.values()):
            raise error("CONTINUOUS_RESULTS_INVALID","Kernel result histories must retain their qualified arrays")
        with self.store.lock:
            if self.store.closed:raise error("CONTINUOUS_STORE_CLOSED","Continuous strategy store is closed")
            projection=self.store.epochs.projection(run_id)
            previous=None if initial else self.store.db.execute(f"SELECT * FROM {projection.heads} WHERE run_id=?",(projection.key,)).fetchone()
            active=[] if previous is None else self.store.db.execute(
                f"SELECT item_index,stored_bytes,wire FROM {projection.items} INDEXED BY {projection.active_index} "
                "WHERE run_id=? AND kind='orders' AND active=1 ORDER BY item_index",
                (projection.key,)).fetchall()
            tail=None if previous is None else self.store.db.execute(
                f"SELECT item_index,stored_bytes,wire FROM {projection.items} WHERE run_id=? AND kind='equity_curve' ORDER BY item_index DESC LIMIT 1",
                (projection.key,)).fetchone()
        counts={kind:len(arrays[kind]) for kind in KINDS}
        before={kind:0 for kind in KINDS} if previous is None else json.loads(previous["counts_json"])
        if any(counts[kind]<before[kind] for kind in KINDS):
            raise error("CONTINUOUS_RESULTS_INVALID","Continuing result histories cannot silently shrink")
        updates={("orders",row["item_index"]):(row["stored_bytes"],row["wire"]) for row in active}
        if tail is not None:updates[("equity_curve",tail["item_index"])]=(tail["stored_bytes"],tail["wire"])
        account={key:value for key,value in engine["account"].items() if key!="journal"}
        head={"account":account,"valuation":valuation(account),"fee_total":engine.get("fee_total"),"ambiguity_count":engine.get("ambiguity_count",0),
            "market_event_count":engine.get("market_event_count",0),"paused":bool(engine.get("paused",False)),
            "decision_count":engine.get("decision_count",len(arrays["decisions"])),
            "decision_chain_hash":engine.get("decision_chain_hash"),
            "latest_equity":arrays["equity_curve"][-1] if arrays["equity_curve"] else None}
        head_json=encode(head,MAX_HEAD_BYTES)
        counts_json=encode(counts,4096)
        stored_bytes=(0 if previous is None else previous["stored_bytes"]
            -len(previous["head_json"].encode("utf-8"))-len(previous["counts_json"].encode("utf-8"))-HEAD_OVERHEAD_BYTES)
        items=[]
        def record(kind,index,old_bytes,old_wire=None):
            nonlocal stored_bytes
            value=arrays[kind][index]
            wire=encode(value,MAX_ITEM_BYTES)
            if old_wire==wire:return
            size=len(wire.encode("utf-8"))+ENTRY_OVERHEAD_BYTES
            active_order=int(kind=="orders" and isinstance(value,Mapping) and value.get("status") in {"OPEN","PARTIAL"})
            items.append(ResultItem(kind,index,wire,size,active_order,old_bytes))
            stored_bytes+=size-old_bytes
        for (kind,index),(old_bytes,old_wire) in updates.items():record(kind,index,old_bytes,old_wire)
        for kind in KINDS:
            # Direct index access only: no iteration over already indexed history.
            for index in range(before[kind],counts[kind]):record(kind,index,0)
        stored_bytes+=len(head_json.encode("utf-8"))+len(counts_json.encode("utf-8"))+HEAD_OVERHEAD_BYTES
        if not initial and stored_bytes>self.store.max_total_checkpoint_bytes:
            raise error("BUDGET_EXCEEDED","Continuous results reached the total disk budget; committed recovery points are retained")
        return ResultPatch(run_id,initial,None if previous is None else previous["checkpoint_revision"],
            head_json,counts_json,stored_bytes,tuple(items))

    def publish(self,run_id,revision,patch):
        """Under the financial SQLite transaction; no user code or encoding."""
        if patch is None:return
        if not isinstance(patch,ResultPatch) or patch.run_id!=run_id:
            raise error("CONTINUOUS_COMMIT_CONFLICT","Result patch belongs to another account")
        projection=self.store.epochs.projection(run_id)
        previous=self.store.db.execute(f"SELECT checkpoint_revision FROM {projection.heads} WHERE run_id=?",(projection.key,)).fetchone()
        if (None if previous is None else previous[0])!=patch.base_checkpoint_revision:
            raise error("CONTINUOUS_COMMIT_CONFLICT","Result projection changed after preparation")
        self.store.db.executemany(f"INSERT INTO {projection.items} VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(run_id,kind,item_index) DO UPDATE SET changed_revision=excluded.changed_revision,"
            "wire=excluded.wire,stored_bytes=excluded.stored_bytes,active=excluded.active",
            ((projection.key,item.kind,item.index,revision,item.wire,item.stored_bytes,item.active) for item in patch.items))
        self.store.db.execute(f"INSERT INTO {projection.heads} VALUES(?,?,?,?,?) ON CONFLICT(run_id) DO UPDATE SET "
            "checkpoint_revision=excluded.checkpoint_revision,head_json=excluded.head_json,"
            "counts_json=excluded.counts_json,stored_bytes=excluded.stored_bytes",
            (projection.key,revision,patch.head_json,patch.counts_json,patch.stored_bytes))

    def ensure(self,run_id):
        """One-time index of legacy state, without changing the financial run.

        Schema migration creates only empty tables. A full old checkpoint is
        decoded here only when requested, outside the commit lock. Failure or
        budget exhaustion leaves its old account and recovery data readable.
        """
        with self.store.lock:
            row=self.store.summary(run_id)
            projection=self.store.epochs.projection(run_id)
            current=self.store.db.execute(f"SELECT checkpoint_revision FROM {projection.heads} WHERE run_id=?",(projection.key,)).fetchone()
            if current is not None and current[0]==row["checkpoint_revision"]:return
        saved=self.store.load(run_id)
        patch=self.prepare(run_id,saved["checkpoint"]["engine"])
        if patch is None:raise error("CONTINUOUS_RESULTS_UNAVAILABLE","Legacy recovery state has no qualified result projection")
        with self.store._transaction():
            current=self.store.summary(run_id)
            if current["checkpoint_revision"]!=saved["run"]["checkpoint_revision"]:
                raise error("CONTINUOUS_COMMIT_CONFLICT","Financial state advanced during legacy result preparation")
            projection=self.store.epochs.projection(run_id)
            head=self.store.db.execute(f"SELECT checkpoint_revision FROM {projection.heads} WHERE run_id=?",(projection.key,)).fetchone()
            if head is not None and head[0]==current["checkpoint_revision"]:return
            self.publish(run_id,current["checkpoint_revision"],patch)
            self.store._enforce_total_budget()

    @staticmethod
    def identity(row):
        return {key:row[key] for key in ("id","generation","revision","checkpoint_revision","sequence","event_time_ms","data_revision")}

    def read(self,run_id,*,kind=None,after=-1,limit=100,expected=None,since_revision=None,change_cursor=None):
        """One bounded page/current summary. Older views must explicitly refresh.

        A full collection page is ordered by zero-based index. A change page
        coalesces current rows changed since a checkpoint, ordered by
        (changed_revision,kind,index). Pagination always requires the exact
        initial identity, preventing mixed generations or commit snapshots.
        """
        from .continuous_store import _text, _counter
        _text(run_id,128)
        if type(limit) is not int or not 1<=limit<=MAX_PAGE_ITEMS or type(after) is not int or not -1<=after<=9_007_199_254_740_991:
            raise error("CONTINUOUS_INPUT_INVALID","Invalid result page budget or cursor")
        if kind is not None and (type(kind) is not str or kind not in KINDS):
            raise error("CONTINUOUS_INPUT_INVALID","Unknown result collection")
        if since_revision is not None and (type(since_revision) is not int or since_revision<0 or kind is not None or after!=-1):
            raise error("CONTINUOUS_INPUT_INVALID","Invalid result change cursor")
        if since_revision is not None:_counter(since_revision)
        if expected is not None:
            fields={"id","generation","revision","checkpoint_revision","sequence","event_time_ms","data_revision"}
            if not isinstance(expected,Mapping) or set(expected)!=fields:
                raise error("CONTINUOUS_INPUT_INVALID","A result identity requires its complete committed cursor")
            _text(expected["id"],128);_text(expected["data_revision"],256)
            for key in fields-{"id","data_revision"}:_counter(expected[key])
        if after!=-1 and (kind is None or expected is None):
            raise error("CONTINUOUS_INPUT_INVALID","A result page requires its initial committed identity")
        if change_cursor is not None:
            if (since_revision is None or expected is None or not isinstance(change_cursor,(tuple,list)) or len(change_cursor)!=3
                    or type(change_cursor[0]) is not int or change_cursor[0]<=since_revision
                    or type(change_cursor[1]) is not str or change_cursor[1] not in KINDS
                    or type(change_cursor[2]) is not int or change_cursor[2]<0):
                raise error("CONTINUOUS_INPUT_INVALID","Invalid result change page cursor")
            _counter(change_cursor[0]);_counter(change_cursor[2])
        # Explicit read transaction: no source/write fence, and another local
        # connection can commit while every SELECT below sees this snapshot.
        with self.store.lock:
            if self.store.closed:raise error("CONTINUOUS_STORE_CLOSED","Continuous strategy store is closed")
            self.store.db.execute("BEGIN")
            try:
                row=self.store.summary(run_id)
                identity=self.identity(row)
                if expected is not None and expected!=identity:
                    raise error("CONTINUOUS_COMMIT_CONFLICT","Result identity changed; refresh the committed view")
                projection=self.store.epochs.projection(run_id)
                head=self.store.db.execute(f"SELECT * FROM {projection.heads} WHERE run_id=?",(projection.key,)).fetchone()
                if head is None or head["checkpoint_revision"]!=row["checkpoint_revision"]:
                    raise error("CONTINUOUS_RESULTS_UNAVAILABLE","Prepare the committed result projection before reading")
                if since_revision is not None and since_revision>row["checkpoint_revision"]:
                    raise error("CONTINUOUS_COMMIT_CONFLICT","Result change cursor is ahead of the account")
                if change_cursor is not None and change_cursor[0]>row["checkpoint_revision"]:
                    raise error("CONTINUOUS_COMMIT_CONFLICT","Result change page is ahead of the account")
                if since_revision is not None:
                    cursor=change_cursor or (since_revision,"",-1)
                    rows=self.store.db.execute(f"SELECT kind,item_index,changed_revision,stored_bytes FROM {projection.items} "
                        "WHERE run_id=? AND changed_revision>? AND (changed_revision,kind,item_index)>(?,?,?) "
                        "ORDER BY changed_revision,kind,item_index LIMIT ?",(projection.key,since_revision,*cursor,limit+1)).fetchall()
                elif kind is not None:
                    rows=self.store.db.execute(f"SELECT kind,item_index,changed_revision,stored_bytes FROM {projection.items} "
                        "WHERE run_id=? AND kind=? AND item_index>? ORDER BY item_index LIMIT ?",(projection.key,kind,after,limit+1)).fetchall()
                else:rows=[]
                items=[];used=len(head["head_json"].encode("utf-8"))+len(head["counts_json"].encode("utf-8"))+8192
                for item in rows[:limit]:
                    size=item["stored_bytes"]
                    if not ENTRY_OVERHEAD_BYTES<=size<=MAX_ITEM_BYTES+ENTRY_OVERHEAD_BYTES:
                        raise error("CONTINUOUS_RESULTS_INVALID","Stored result item size is outside its budget")
                    if used+size>MAX_PAGE_BYTES:break
                    wire=self.store.db.execute(f"SELECT wire FROM {projection.items} WHERE run_id=? AND kind=? AND item_index=?",
                        (projection.key,item["kind"],item["item_index"])).fetchone()[0]
                    if len(wire.encode("utf-8"))+ENTRY_OVERHEAD_BYTES!=size:
                        raise error("CONTINUOUS_RESULTS_INVALID","Stored result item size does not match its payload")
                    items.append({"kind":item["kind"],"index":item["item_index"],"changed_revision":item["changed_revision"],"value":json.loads(wire)})
                    used+=size
                more=len(rows)>len(items)
                next_cursor=None
                if more and items:
                    last=items[-1]
                    next_cursor=[last["changed_revision"],last["kind"],last["index"]] if since_revision is not None else last["index"]
                return {"run":row,"identity":identity,"summary":json.loads(head["head_json"]),
                    "counts":json.loads(head["counts_json"]),"items":items,"more":more,"next_cursor":next_cursor,
                    "stale":row["phase"]=="REPAIR_REQUIRED"}
            finally:self.store.db.execute("ROLLBACK")
