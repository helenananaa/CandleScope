"""Admission-time ADL cohorts for markets added to a modelled HEDGE account.

The original simulation and its insurance ledger stay immutable. These small,
independently versioned inputs become effective only when a track is admitted.
They are committed in the same transaction as the track's public input binding.
"""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from decimal import Decimal

from app.replay.canonical import canonical_json, canonical_sha256

SCHEMA = "replay.hybrid-adl-extension.v1"


def build_extension(*, symbol: str, settlement_asset: str, base_manifest_id: str,
                    base_checksum: str, public_archive_id: str, public_checksum: str,
                    actual_time_ms: int, virtual_time_ms: int, end_time_ms: int,
                    price: str, leverage: str) -> dict[str, object]:
    mark, maximum = Decimal(price), Decimal(leverage)
    if not mark.is_finite() or mark <= 0 or not maximum.is_finite() or maximum < 1:
        raise ValueError("hybrid admission requires a positive revealed mark and leverage")
    if end_time_ms < actual_time_ms:
        raise ValueError("hybrid admission exceeds the bound training range")
    margin = mark / maximum
    candidates = [{
        "candidate_id": f"hybrid-added-{symbol.lower()}-{side.lower()}",
        "symbol": symbol, "position_side": side, "quantity": "1",
        "entry_price": format(mark * ratio, "f"), "mark_price": format(mark, "f"),
        "initial_margin": format(margin, "f"), "margin_balance": format(margin * 2, "f"),
    } for side, ratio in (("LONG", Decimal("0.9")), ("SHORT", Decimal("1.1")))]
    snapshot = {"sequence": 1, "symbol": symbol, "effective_time_ms": virtual_time_ms,
                "valid_until_ms": virtual_time_ms + end_time_ms - actual_time_ms,
                "candidates": candidates}
    payload = {"schema_version": SCHEMA, "settlement_asset": settlement_asset,
               "base_manifest_id": base_manifest_id, "base_checksum": base_checksum,
               "public_archive_id": public_archive_id, "public_checksum": public_checksum,
               "actual_time_ms": actual_time_ms, "virtual_time_ms": virtual_time_ms,
               "end_time_ms": end_time_ms, "snapshot": snapshot}
    snapshot["snapshot_hash"] = canonical_sha256(payload)
    return payload


def extension_rows(connection: sqlite3.Connection, run_id: str) -> list[dict[str, object]]:
    return [dict(row) for row in connection.execute(
        "SELECT * FROM replay_hedge_hybrid_extension WHERE run_id=? ORDER BY track_id", (run_id,))]


def validate_extension(row: Mapping[str, object]) -> dict[str, object]:
    payload = json.loads(str(row["payload_json"]))
    if payload.get("schema_version") != SCHEMA or canonical_sha256(payload) != row["component_hash"]:
        raise ValueError("hybrid ADL extension is corrupt or incompatible")
    snapshot = payload["snapshot"]
    unsigned = {**payload, "snapshot": {k: v for k, v in snapshot.items() if k != "snapshot_hash"}}
    if canonical_sha256(unsigned) != snapshot["snapshot_hash"]:
        raise ValueError("hybrid ADL cohort is corrupt")
    return payload


def bind_extension(connection: sqlite3.Connection, *, run_id: str, track_id: str,
                   payload: Mapping[str, object], now_ms: int) -> None:
    root = connection.execute("SELECT * FROM replay_hedge_input_binding WHERE run_id=?", (run_id,)).fetchone()
    track = connection.execute("SELECT * FROM replay_hedge_track_public_binding WHERE run_id=? AND track_id=?", (run_id, track_id)).fetchone()
    if (root is None or track is None or root["status"] != "ACTIVE"
            or root["simulation_manifest_id"] != payload["base_manifest_id"]
            or root["simulation_checksum_sha256"] != payload["base_checksum"]
            or track["public_archive_id"] != payload["public_archive_id"]
            or track["public_checksum_sha256"] != payload["public_checksum"]):
        raise ValueError("hybrid admission input changed before commit")
    encoded, digest = canonical_json(payload), canonical_sha256(payload)
    validate_extension({"payload_json": encoded, "component_hash": digest})
    connection.execute("INSERT INTO replay_hedge_hybrid_extension(run_id,track_id,payload_json,component_hash,created_at_ms) VALUES(?,?,?,?,?)",
                       (run_id, track_id, encoded, digest, now_ms))


def extension_snapshot(connection: sqlite3.Connection, *, run_id: str, symbol: str) -> Mapping[str, object] | None:
    row = connection.execute("""SELECT extension.payload_json FROM replay_hedge_hybrid_extension extension
        JOIN replay_training_market_track track USING(run_id,track_id)
        WHERE extension.run_id=? AND track.symbol=?""", (run_id, symbol)).fetchone()
    # Already validated at admission/load/audit. Do not add hashing to each risk event.
    return None if row is None else json.loads(row["payload_json"])["snapshot"]
