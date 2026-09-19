"""Durable, directly addressed history chunks for host-owned simulation kernels.

Terminal order prefixes and frozen fills are sealed; optional trade V2 also
seals owned append-only decision/event streams. Active orders and mutable state
remain in each checkpoint. No preceding checkpoint is needed.
"""
import json

from app.core.config import getenv

from .errors import BacktestError
from .identity import canonical_json, sha256_hex

ENCODING = "BAR_HISTORY_CHUNKS_V1"
TRADE_ENCODING = "TRADE_HISTORY_CHUNKS_V1"
EXTENDED_TRADE_ENCODING = "TRADE_HISTORY_CHUNKS_V2"
CHUNK_SIZE = 256


class HistoryEncoder:
    def __init__(self, encode_record, *, extended=False):
        self.encode_record = encode_record
        self.extended = extended
        self.streams = {}
        self.pending = {}
        self.logical_extra = 0
        # Candidate stays opt-in until long-run service timing is stable.
        self.reuse_encoding = getenv("BACKTEST_REUSE_HISTORY_JSON_ENABLED", "0").strip() == "1"
        self.fragments = {}

    def begin(self):
        self.logical_extra = 0
        self.fragments.clear()

    def __call__(self, name, rows):
        stream = self.streams.get(name)
        if stream is None or stream[0] is not rows or len(rows) < stream[1]:
            stream = [rows, 0, [], 0]  # list identity, sealed count, hashes, inner JSON bytes
            self.streams[name] = stream
        while len(rows) - stream[1] >= CHUNK_SIZE:
            batch = rows[stream[1]:stream[1] + CHUNK_SIZE]
            if name == "orders" and any(row.status in {"OPEN", "PARTIAL"} for row in batch):
                break
            raw = canonical_json([self.encode_record(row) for row in batch])
            digest = "sha256:" + sha256_hex(raw)
            self.pending[digest] = raw
            stream[2].append(digest)
            stream[3] += len(raw.encode("utf-8")) - 2 + bool(stream[1])
            stream[1] += CHUNK_SIZE
        tail = [self.encode_record(row) for row in rows[stream[1]:]]
        manifest = {"chunks": list(stream[2]), "tail": tail}
        tail_json = canonical_json(tail)
        if self.reuse_encoding:
            manifest_json = '{"chunks":' + canonical_json(manifest["chunks"]) + ',"tail":' + tail_json + '}'
            self.fragments[id(manifest)] = (manifest, manifest_json)
        else:
            manifest_json = canonical_json(manifest)
        full_size = stream[3] + len(tail_json.encode("utf-8")) + bool(stream[1] and tail)
        self.logical_extra += full_size - len(manifest_json.encode("utf-8"))
        return manifest


def history_engine(payload):
    engine = payload["engine"]
    return engine["execution"] if payload.get("checkpointMode") == "DUAL_CLOCK" else engine


def history_locations(payload):
    encoding, mode = payload["historyEncoding"], payload.get("checkpointMode")
    if (encoding, mode) not in {
        (ENCODING, "BAR"), (TRADE_ENCODING, "TRADE_TAPE"), (TRADE_ENCODING, "DUAL_CLOCK"),
        (EXTENDED_TRADE_ENCODING, "TRADE_TAPE"), (EXTENDED_TRADE_ENCODING, "DUAL_CLOCK"),
    }:
        raise ValueError("unsupported checkpoint history encoding")
    engine = history_engine(payload)
    names = ["orders", "fills"]
    if encoding == EXTENDED_TRADE_ENCODING:
        names.append("decisions")
        if "execution_model_revision" in engine:
            names.extend(("order_events", "fill_source_events", "frozen_intents"))
    locations = [(engine, name) for name in names]
    if encoding == EXTENDED_TRADE_ENCODING and mode == "DUAL_CLOCK":
        locations.append((payload["engine"], "decisions"))
        if "execution_model_revision" in engine:
            locations.append((payload["engine"], "frozen_intents"))
    return locations


def referenced_chunks(payload):
    if "historyEncoding" not in payload:
        return set()
    references = set()
    for owner, name in history_locations(payload):
        manifest = owner[name]
        if (type(manifest) is not dict or set(manifest) != {"chunks", "tail"}
                or type(manifest["chunks"]) is not list or type(manifest["tail"]) is not list):
            raise ValueError("invalid checkpoint history manifest")
        for digest in manifest["chunks"]:
            if type(digest) is not str or len(digest) != 71 or not digest.startswith("sha256:"):
                raise ValueError("invalid checkpoint chunk address")
            references.add(digest)
    return references


def trade_history_encoder():
    from dataclasses import asdict
    from app.core.config import getenv

    from app.simulation.kernel import _flat_record
    record_encoder = (_flat_record if getenv("BACKTEST_FLAT_TRADE_RECORDS_ENABLED", "1").strip() == "1"
                      else asdict)

    def encode(row):
        return dict(row) if type(row) is dict else record_encoder(row)

    return HistoryEncoder(encode, extended=getenv("BACKTEST_EXTENDED_TRADE_HISTORY_ENABLED", "1").strip() == "1")


def expand_checkpoint(row, connection):
    """Validate stored bytes before exposing the legacy, fully detached payload."""
    try:
        payload = json.loads(row["payload_json"])
        if "historyEncoding" not in payload:
            return row
        if row["state_hash"] != "sha256:" + sha256_hex(payload):
            raise ValueError("checkpoint manifest hash mismatch")
        references = referenced_chunks(payload)
        chunks = {}
        for digest in references:
            stored = connection.execute(
                "SELECT payload_json FROM backtest_checkpoint_chunks WHERE run_id=? AND chunk_hash=?",
                (row["run_id"], digest),
            ).fetchone()
            if stored is None or "sha256:" + sha256_hex(stored[0]) != digest:
                raise ValueError("checkpoint history chunk missing or corrupt")
            chunk = json.loads(stored[0])
            if type(chunk) is not list or len(chunk) != CHUNK_SIZE or any(type(item) is not dict for item in chunk):
                raise ValueError("invalid checkpoint history chunk")
            chunks[digest] = chunk
        for owner, name in history_locations(payload):
            manifest = owner[name]
            owner[name] = [item for digest in manifest["chunks"] for item in chunks[digest]] + manifest["tail"]
        del payload["historyEncoding"]
        raw = canonical_json(payload)
        return {**row, "payload_json": raw, "state_hash": "sha256:" + sha256_hex(raw)}
    except (KeyError, TypeError, ValueError) as exc:
        raise BacktestError("CHECKPOINT_CORRUPT", str(exc)) from exc


def publish_chunks(connection, row):
    if row.get("history_chunks") is None:
        connection.execute("DELETE FROM backtest_checkpoint_chunks WHERE run_id=?", (row["run_id"],))
        return
    payload = json.loads(row["payload_json"])
    references = referenced_chunks(payload)
    for digest, raw in row.get("history_chunks", {}).items():
        if digest not in references:
            continue
        if "sha256:" + sha256_hex(raw) != digest:
            raise ValueError("checkpoint chunk hash mismatch")
        connection.execute(
            "INSERT OR IGNORE INTO backtest_checkpoint_chunks VALUES (?, ?, ?)",
            (row["run_id"], digest, raw),
        )
    stored = {item[0] for item in connection.execute(
        "SELECT chunk_hash FROM backtest_checkpoint_chunks WHERE run_id=?", (row["run_id"],))}
    if references - stored:
        raise ValueError("checkpoint refers to missing history")
    connection.executemany(
        "DELETE FROM backtest_checkpoint_chunks WHERE run_id=? AND chunk_hash=?",
        ((row["run_id"], digest) for digest in stored - references),
    )


def materialize_histories(connection):
    """Caller holds an offline write transaction; corruption aborts downgrade."""
    rows = connection.execute("SELECT * FROM backtest_checkpoints").fetchall()
    for row in rows:
        full = expand_checkpoint(dict(row), connection)
        connection.execute(
            "UPDATE backtest_checkpoints SET payload_json=?, state_hash=? WHERE run_id=? AND sequence=?",
            (full["payload_json"], full["state_hash"], full["run_id"], full["sequence"]),
        )
    connection.execute("DROP TABLE backtest_checkpoint_chunks")


def rollback_history(database):
    """Offline v8/v9 -> v7 rollback. Materialize reports and checkpoints atomically."""
    import sqlite3
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("BEGIN IMMEDIATE")
        version = connection.execute("SELECT schema_version FROM backtest_schema_meta").fetchone()[0]
        if version not in {8, 9}:
            raise RuntimeError("history rollback requires schema version 8 or 9")
        if version == 9:
            from .report_storage import materialize_reports
            materialize_reports(connection)
        materialize_histories(connection)
        connection.execute("UPDATE backtest_schema_meta SET schema_version=7")
        connection.commit()
        return {"schemaVersion": 7, "checkpointsMaterialized": True}
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()
