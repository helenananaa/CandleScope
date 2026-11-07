"""Bounded durable consumer prefix fences; no per-row event or OHLC copies.

Each canonical mutation updates only overlapping registered prefixes in the same
SQLite transaction. The independent version counter avoids trigger-order
assumptions about D126's existing global clock.
"""
from __future__ import annotations

from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from uuid import uuid4

from .revisions import IDENTITY_COLUMNS, REVISION_CHANGED_FIELDS, current_revision, StaleAcquisition

MAX_WATCHES = 128
MIN_TIME = -9_007_199_254_740_991
MAX_TIME = 9_007_199_254_740_991


class PrefixContinuityUnavailable(StaleAcquisition):
    """The old source identity or continuity can no longer be proved."""


class PrefixAcquisitionChanged(StaleAcquisition):
    def __init__(self,start_ms,end_ms):
        super().__init__("source prefix changed while the new batch was being acquired")
        self.start_ms,self.end_ms=start_ms,end_ms


class ProcessedPrefixChanged(PrefixAcquisitionChanged):
    def __init__(self, start_ms, end_ms):
        StaleAcquisition.__init__(self,"processed source prefix changed; explicit repair is required")
        self.start_ms, self.end_ms = start_ms, end_ms


def init_prefix_watch_storage(conn):
    columns = ",".join(f"{key} TEXT NOT NULL" for key in IDENTITY_COLUMNS)
    conn.execute(f"""CREATE TABLE IF NOT EXISTS kline_prefix_watches (
        owner TEXT PRIMARY KEY, incarnation TEXT NOT NULL, {columns},
        from_ms INTEGER NOT NULL, through_ms INTEGER NOT NULL,
        acquisition INTEGER NOT NULL, version INTEGER NOT NULL, registered_storage_revision INTEGER NOT NULL,
        verified_through_ms INTEGER NOT NULL, verified_version INTEGER NOT NULL,
        committed_acquisition INTEGER NOT NULL, committed_through_ms INTEGER NOT NULL,
        dirty_from_ms INTEGER, dirty_through_ms INTEGER)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_kline_prefix_watches_through ON kline_prefix_watches("+
                 ",".join(IDENTITY_COLUMNS)+",through_ms,from_ms)")
    conn.execute("DROP INDEX IF EXISTS idx_kline_prefix_watches_series")
    for operation,alias in (("insert","NEW"),("update","NEW"),("delete","OLD")):
        changed = "WHEN " + " OR ".join(f"NEW.{key} IS NOT OLD.{key}" for key in REVISION_CHANGED_FIELDS) if operation == "update" else ""
        where = " AND ".join(f"{key}={alias}.{key}" for key in IDENTITY_COLUMNS)
        stamp = f"{alias}.open_time"
        end = ("MAX(COALESCE(OLD.close_time,OLD.open_time),COALESCE(NEW.close_time,NEW.open_time),NEW.open_time)"
               if operation == "update" else f"MAX(COALESCE({alias}.close_time,{alias}.open_time),{alias}.open_time)")
        conn.execute(f"""CREATE TRIGGER IF NOT EXISTS kline_prefix_watch_{operation}
            AFTER {operation.upper()} ON klines {changed} BEGIN
            UPDATE kline_prefix_watches SET version=version+1,
                dirty_from_ms=CASE WHEN dirty_from_ms IS NULL THEN {stamp} ELSE MIN(dirty_from_ms,{stamp}) END,
                dirty_through_ms=CASE WHEN dirty_through_ms IS NULL THEN {end} ELSE MAX(dirty_through_ms,{end}) END
            WHERE {where} AND from_ms<=through_ms AND from_ms<={end} AND through_ms>={stamp}; END""")


def invalidate_deleted_prefix(conn, values, start_ms, end_ms):
    start, end = MIN_TIME if start_ms is None else start_ms, MAX_TIME if end_ms is None else end_ms
    conn.execute("UPDATE kline_prefix_watches SET version=version+1,"
        "dirty_from_ms=CASE WHEN dirty_from_ms IS NULL THEN ? ELSE MIN(dirty_from_ms,?) END,"
        "dirty_through_ms=CASE WHEN dirty_through_ms IS NULL THEN ? ELSE MAX(dirty_through_ms,?) END WHERE "+
        " AND ".join(f"{key}=?" for key in IDENTITY_COLUMNS)+" AND from_ms<=through_ms AND from_ms<=? AND through_ms>=?",
        (start,start,end,end,*values,end,start))


def _time(value):
    if type(value) is not int or not MIN_TIME <= value <= MAX_TIME:
        raise ValueError("prefix time must be a safe integer")
    return value


def _scope(owner,series):
    if not isinstance(owner,str) or not 1 <= len(owner) <= 128:
        raise ValueError("prefix owner must be bounded")
    if not isinstance(series,(tuple,list)):
        raise ValueError("prefix requires an ordered series identity")
    values = tuple(series)
    if len(values) != len(IDENTITY_COLUMNS) or any(not isinstance(value,str) or not 1 <= len(value) <= 256 for value in values):
        raise ValueError("prefix requires a complete semantic series identity")
    return values


@dataclass(frozen=True)
class PrefixReceipt:
    owner: str
    incarnation: str
    series: tuple[str,...]
    acquisition: int
    version: int
    storage_revision: int
    from_ms: int
    through_ms: int

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls,value):
        if not isinstance(value,dict) or set(value) != set(cls.__dataclass_fields__):
            raise PrefixContinuityUnavailable("source prefix receipt is unavailable")
        try:
            values=_scope(value["owner"],value["series"])
            _time(value["from_ms"]);_time(value["through_ms"])
            if (not isinstance(value["incarnation"],str) or not 1 <= len(value["incarnation"]) <= 128
                    or any(type(value[key]) is not int or not 0 <= value[key] <= MAX_TIME for key in ("acquisition","version","storage_revision"))):
                raise ValueError
            return cls(**{**value,"series":values})
        except (KeyError,TypeError,ValueError) as error:
            raise PrefixContinuityUnavailable("source prefix receipt is invalid") from error


class PrefixWatchStore:
    def __init__(self,connect,*,max_watches=MAX_WATCHES):
        if type(max_watches) is not int or max_watches < 1:
            raise ValueError("prefix watch budget must be positive")
        self.connect,self.max_watches=connect,max_watches

    @staticmethod
    def _receipt(row,revision):
        return PrefixReceipt(row["owner"],row["incarnation"],tuple(row[key] for key in IDENTITY_COLUMNS),
            row["acquisition"],row["version"],revision,row["from_ms"],row["through_ms"])

    @staticmethod
    def _matching(row,receipt):
        if (row is None or row["incarnation"] != receipt.incarnation or row["owner"] != receipt.owner
                or tuple(row[key] for key in IDENTITY_COLUMNS) != receipt.series or row["from_ms"] != receipt.from_ms):
            raise PrefixContinuityUnavailable("source watch disappeared or changed identity")

    def register(self,owner,series,*,from_ms,committed_through_ms):
        values=_scope(owner,series);_time(from_ms);_time(committed_through_ms)
        if committed_through_ms >= from_ms:
            raise ValueError("register a new watch before its first input is processed")
        with closing(self.connect()) as conn,conn:
            conn.execute("BEGIN IMMEDIATE")
            row=conn.execute("SELECT * FROM kline_prefix_watches WHERE owner=?",(owner,)).fetchone()
            if row is not None:
                if (tuple(row[key] for key in IDENTITY_COLUMNS) == values and row["from_ms"] == from_ms
                        and row["through_ms"] == committed_through_ms and row["acquisition"] == 0):
                    return self._receipt(row,row["registered_storage_revision"])
                raise PrefixContinuityUnavailable("source owner already has a watch; recover its original receipt")
            if conn.execute("SELECT count(*) FROM kline_prefix_watches").fetchone()[0] >= self.max_watches:
                raise PrefixContinuityUnavailable("source prefix watch capacity reached")
            columns="owner,incarnation,"+",".join(IDENTITY_COLUMNS)+",from_ms,through_ms,acquisition,version,registered_storage_revision,verified_through_ms,verified_version,committed_acquisition,committed_through_ms"
            params=(owner,uuid4().hex,*values,from_ms,committed_through_ms,0,0,current_revision(conn),committed_through_ms,0,0,committed_through_ms)
            conn.execute("INSERT INTO kline_prefix_watches("+columns+") VALUES("+",".join("?" for _ in params)+")",params)
            row=conn.execute("SELECT * FROM kline_prefix_watches WHERE owner=?",(owner,)).fetchone()
            return self._receipt(row,current_revision(conn))

    def prepare(self,receipt: PrefixReceipt,*,committed_through_ms,through_ms,frozen_version=None):
        _time(committed_through_ms);_time(through_ms)
        if frozen_version is not None and (type(frozen_version) is not int or not 0 <= frozen_version <= MAX_TIME):
            raise ValueError("frozen source version must be a safe counter")
        if receipt.through_ms != committed_through_ms or through_ms < committed_through_ms:
            raise PrefixContinuityUnavailable("financial cursor and source receipt do not agree")
        with closing(self.connect()) as conn,conn:
            conn.execute("BEGIN IMMEDIATE")
            row=conn.execute("SELECT * FROM kline_prefix_watches WHERE owner=?",(receipt.owner,)).fetchone()
            self._matching(row,receipt)
            head=current_revision(conn)
            if (head < receipt.storage_revision or row["version"] < receipt.version or row["through_ms"] < committed_through_ms
                    or receipt.acquisition > row["acquisition"]):
                raise PrefixContinuityUnavailable("source database no longer covers the committed receipt")
            if receipt.acquisition < row["committed_acquisition"] or committed_through_ms < row["committed_through_ms"]:
                raise PrefixContinuityUnavailable("financial receipt is older than acknowledged source progress")
            if frozen_version is not None and row["version"] != frozen_version:
                raise ProcessedPrefixChanged(max(receipt.from_ms,row["dirty_from_ms"] or receipt.from_ms),
                                             row["dirty_through_ms"] if row["dirty_through_ms"] is not None else row["through_ms"])
            observed=receipt.version
            if row["verified_through_ms"] >= committed_through_ms:
                observed=max(observed,row["verified_version"])
            if row["version"] > observed:
                if row["dirty_from_ms"] is None:
                    raise PrefixContinuityUnavailable("source prefix changes cannot be located")
                if committed_through_ms >= receipt.from_ms and row["dirty_from_ms"] <= committed_through_ms:
                    raise ProcessedPrefixChanged(max(receipt.from_ms,row["dirty_from_ms"]),min(committed_through_ms,row["dirty_through_ms"]))
            conn.execute("UPDATE kline_prefix_watches SET through_ms=?,acquisition=acquisition+1,"
                "verified_through_ms=?,verified_version=version,dirty_from_ms=NULL,dirty_through_ms=NULL WHERE owner=?",
                (through_ms,committed_through_ms,receipt.owner))
            return self._receipt(conn.execute("SELECT * FROM kline_prefix_watches WHERE owner=?",(receipt.owner,)).fetchone(),head)

    def fork_unchanged(self,receipt: PrefixReceipt,owner,*,through_ms,expected_version):
        """Explicit repair may reuse only a prefix before the earliest revision.

        This creates a separate durable source epoch before any financial swap.
        It neither rewinds nor renames the original watch, so a crash before or
        after financial publication cannot strand a receipt behind a rename.
        """
        receipt=PrefixReceipt.from_dict(receipt.to_dict())
        values=_scope(owner,receipt.series);_time(through_ms)
        if (type(expected_version) is not int or not receipt.version<=expected_version<=MAX_TIME
                or owner==receipt.owner or not receipt.from_ms-1<=through_ms<=receipt.through_ms):
            raise PrefixContinuityUnavailable("repair anchor must stay inside its observed financial prefix")
        with closing(self.connect()) as conn,conn:
            conn.execute("BEGIN IMMEDIATE")
            row=conn.execute("SELECT * FROM kline_prefix_watches WHERE owner=?",(receipt.owner,)).fetchone()
            self._matching(row,receipt)
            head=current_revision(conn)
            if (head<receipt.storage_revision or row["acquisition"]<receipt.acquisition
                    or row["through_ms"]<receipt.through_ms or row["version"]!=expected_version
                    or row["dirty_from_ms"] is None or row["dirty_from_ms"]>receipt.through_ms
                    or through_ms>=row["dirty_from_ms"]):
                raise PrefixContinuityUnavailable("source changed or repair anchor crosses revised history")
            if conn.execute("SELECT 1 FROM kline_prefix_watches WHERE owner=?",(owner,)).fetchone():
                raise PrefixContinuityUnavailable("repair source owner already exists; recover its original receipt")
            if conn.execute("SELECT count(*) FROM kline_prefix_watches").fetchone()[0]>=self.max_watches:
                raise PrefixContinuityUnavailable("source prefix watch capacity reached")
            columns="owner,incarnation,"+",".join(IDENTITY_COLUMNS)+",from_ms,through_ms,acquisition,version,registered_storage_revision,verified_through_ms,verified_version,committed_acquisition,committed_through_ms"
            params=(owner,uuid4().hex,*values,receipt.from_ms,through_ms,0,0,head,through_ms,0,0,through_ms)
            conn.execute("INSERT INTO kline_prefix_watches("+columns+") VALUES("+",".join("?" for _ in params)+")",params)
            return self._receipt(conn.execute("SELECT * FROM kline_prefix_watches WHERE owner=?",(owner,)).fetchone(),head)

    @contextmanager
    def commit_guard(self,proof: PrefixReceipt,*,committed_through_ms=None):
        """Hold only the final source fence/financial commit, never computation."""
        acknowledged = proof.through_ms if committed_through_ms is None else _time(committed_through_ms)
        if not proof.from_ms-1 <= acknowledged <= proof.through_ms:
            raise ValueError("financial commit must stay inside the acquired source prefix")
        with closing(self.connect()) as conn,conn:
            conn.execute("BEGIN IMMEDIATE")
            row=conn.execute("SELECT * FROM kline_prefix_watches WHERE owner=?",(proof.owner,)).fetchone()
            self._matching(row,proof)
            if (row["acquisition"] != proof.acquisition or proof.acquisition < row["committed_acquisition"]
                    or acknowledged < row["committed_through_ms"]
                    or row["through_ms"] != proof.through_ms or current_revision(conn) < proof.storage_revision):
                raise StaleAcquisition("source prefix changed while the new input batch was acquired")
            if row["version"] != proof.version:
                raise PrefixAcquisitionChanged(row["dirty_from_ms"],row["dirty_through_ms"])
            yield
            conn.execute("UPDATE kline_prefix_watches SET verified_through_ms=?,verified_version=version,"
                         "committed_acquisition=?,committed_through_ms=?,dirty_from_ms=NULL,dirty_through_ms=NULL WHERE owner=?",
                         (acknowledged,proof.acquisition,acknowledged,proof.owner))

    def inspect(self,owner):
        with closing(self.connect()) as conn,conn:
            conn.execute("BEGIN")
            row=conn.execute("SELECT * FROM kline_prefix_watches WHERE owner=?",(owner,)).fetchone()
            return None if row is None else {**dict(row),"storage_revision":current_revision(conn)}

    def release(self,receipt: PrefixReceipt):
        with closing(self.connect()) as conn,conn:
            conn.execute("BEGIN IMMEDIATE")
            row=conn.execute("SELECT * FROM kline_prefix_watches WHERE owner=?",(receipt.owner,)).fetchone()
            self._matching(row,receipt)
            if row["acquisition"] != receipt.acquisition:
                raise StaleAcquisition("a newer source acquisition owns this watch")
            conn.execute("DELETE FROM kline_prefix_watches WHERE owner=?",(receipt.owner,))
