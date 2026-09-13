"""Derived, market-only price blocks for already verified public archives."""

import hashlib
import json
import os
import sqlite3
import uuid
import zlib
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

BLOCK = 1024
SCHEMA = "replay.public-price-blocks.v1"


def _signature(path):
    stat = path.stat()
    return [stat.st_size, stat.st_mtime_ns, stat.st_ino]


def _index_path(path):
    return path.with_name(path.name + ".prices.sqlite3")


def _open(path):
    return sqlite3.connect(
        "file:" + quote(path.as_posix(), safe="/:") + "?mode=ro", uri=True
    )


def _metadata(connection, path, checksum):
    row = connection.execute("SELECT value FROM metadata").fetchone()
    meta = json.loads(row[0]) if row else {}
    if (
        meta.get("schema") != SCHEMA
        or meta.get("checksum") != checksum
        or meta.get("signature") != _signature(path)
    ):
        raise ValueError("public price blocks no longer match their source")
    return meta


def prepare_price_blocks(path: Path, checksum: str, events, *, force=False):
    """Publish only after source identity and every immutable block are bound."""
    path = path.resolve(strict=True)
    destination = _index_path(path)
    try:
        if force:
            raise ValueError("rebuild requested")
        with closing(_open(destination)) as connection:
            _metadata(connection, path, checksum)
        return
    except (sqlite3.Error, OSError, ValueError, TypeError):
        pass
    signature = _signature(path)
    if "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
        raise ValueError("public input revision changed during block preparation")
    temporary = destination.with_name(
        destination.name + "." + uuid.uuid4().hex + ".tmp"
    )
    connection = sqlite3.connect(temporary)
    try:
        connection.execute("CREATE TABLE metadata(value TEXT NOT NULL)")
        connection.execute(
            "CREATE TABLE blocks(id INTEGER PRIMARY KEY, value BLOB NOT NULL, digest TEXT NOT NULL)"
        )
        for start in range(0, len(events), BLOCK):
            rows = [
                (
                    e.event_time_ms,
                    e.event_phase,
                    e.event_kind,
                    e.event_sequence,
                    e.payload.get("mark_price"),
                )
                for e in events[start : start + BLOCK]
            ]
            raw = json.dumps(rows, separators=(",", ":")).encode()
            connection.execute(
                "INSERT INTO blocks VALUES (?,?,?)",
                (
                    start // BLOCK,
                    zlib.compress(raw, 1),
                    hashlib.sha256(raw).hexdigest(),
                ),
            )
        if _signature(path) != signature:
            raise ValueError("public input changed during block preparation")
        connection.execute(
            "INSERT INTO metadata VALUES (?)",
            (
                json.dumps(
                    dict(
                        schema=SCHEMA,
                        checksum=checksum,
                        signature=signature,
                        count=len(events),
                    )
                ),
            ),
        )
        connection.commit()
    except BaseException:
        connection.close()
        temporary.unlink(missing_ok=True)
        raise
    connection.close()
    try:
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def read_price_blocks(path: Path, checksum: str, first: int, last: int):
    path = path.resolve(strict=True)
    with closing(_open(_index_path(path))) as connection:
        meta = _metadata(connection, path, checksum)
        if not 0 <= first <= last <= meta["count"]:
            raise ValueError("public price block range changed")
        result = []
        for index in range(first // BLOCK, (last + BLOCK - 1) // BLOCK):
            row = connection.execute(
                "SELECT value,digest FROM blocks WHERE id=?", (index,)
            ).fetchone()
            if row is None:
                raise ValueError("public price block is missing")
            raw = zlib.decompress(row[0])
            if hashlib.sha256(raw).hexdigest() != row[1]:
                raise ValueError("public price block checksum changed")
            values = json.loads(raw)
            expected = min(BLOCK, meta["count"] - index * BLOCK)
            if len(values) != expected:
                raise ValueError("public price block count changed")
            result.extend(
                values[max(0, first - index * BLOCK) : min(BLOCK, last - index * BLOCK)]
            )
        if _signature(path) != meta["signature"]:
            raise ValueError("public input changed during block read")
        return result
