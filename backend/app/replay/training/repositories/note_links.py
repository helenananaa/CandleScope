"""Freeze note references from the existing committed fill/trade and ledger owners."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

from ..errors import TrainingRunError

MAX_LINKS = 8
LINK_FIELDS = {"FILL": "replayFillIds", "TRADE": "replayTradeIds"}
KEYS = {"kind", "id", "fillId", "eventTimeMs", "sourceSequence", "side", "quantity", "price"}


def _error(message: str, *, corrupt: bool = False) -> TrainingRunError:
    return TrainingRunError("REPLAY_NOTE_LINK_CORRUPT" if corrupt else "REPLAY_NOTE_LINK_INVALID",
                            message, status_code=503 if corrupt else 422)


def _ledger_limit(connection: sqlite3.Connection, context: Mapping[str, object]) -> int:
    if context["reviewId"] is None:
        return int(connection.execute("SELECT COALESCE(MAX(ledger_sequence),0) FROM replay_training_contract_ledger "
                                      "WHERE run_id=?", (context["runId"],)).fetchone()[0])
    # The frozen event records the complete ledger prefix, including zero-fee
    # fills. Time alone cannot distinguish later fills at the same millisecond.
    event = connection.execute("SELECT projection_json FROM replay_review_timeline_event "
                               "WHERE run_id=? AND timeline_sequence=?",
                               (context["runId"], context["timelineSequence"])).fetchone()
    try:
        count = json.loads(event[0])["domain"]["ledger_count"]
        if type(count) is not int or count < 0:
            raise ValueError
        return count
    except (TypeError, ValueError, KeyError, IndexError):
        raise _error("Historical ledger prefix is unavailable", corrupt=True) from None


def _valid(link: object) -> bool:
    if not isinstance(link, dict) or set(link) != KEYS or not isinstance(link["kind"], str) or link["kind"] not in LINK_FIELDS or not isinstance(link["side"], str) or link["side"] not in {"BUY", "SELL"}:
        return False
    if any(not isinstance(link[key], str) or not 1 <= len(link[key]) <= 128 for key in ["id", "fillId"]):
        return False
    if any(type(link[key]) is not int or link[key] < 0 for key in ["eventTimeMs", "sourceSequence"]):
        return False
    try:
        return all(isinstance(link[key], str) and len(link[key]) <= 256
                   and Decimal(link[key]).is_finite() and Decimal(link[key]) > 0 for key in ["quantity", "price"])
    except InvalidOperation:
        return False


def _rows(connection: sqlite3.Connection, context: Mapping[str, object], kind: str, *,
          before_id: str | None = None, exact_id: str | None = None, limit: int = 21) -> list[dict[str, object]]:
    if not isinstance(kind, str) or kind not in LINK_FIELDS:
        raise _error("Unsupported annotation reference kind")
    source = "replay_training_contract_fill AS f" if kind == "FILL" else "replay_training_trade_result AS t"
    owner, identity, clock = ("f", "fill_id", "json_extract(f.fill_json,'$.event_time_ms')") if kind == "FILL" else ("t", "trade_id", "t.exit_time_ms")
    join = "" if kind == "FILL" else " JOIN replay_training_contract_fill AS f ON f.run_id=t.run_id AND f.track_id=t.track_id AND f.fill_id=t.fill_id"
    sql = (f"SELECT {owner}.* FROM {source}" + join
        + " JOIN replay_training_contract_ledger AS l ON l.run_id=f.run_id AND l.posting_id='fee:'||f.track_id||':'||f.fill_id "
          "AND l.track_id=f.track_id AND l.reference_type='FILL' AND l.reference_id=f.fill_id "
        + f"WHERE {owner}.run_id=? AND {owner}.track_id=? AND l.ledger_sequence<=? AND {clock}<=?")
    args = [context["runId"], context["trackId"], _ledger_limit(connection, context), context["virtualTimeMs"]]
    if before_id is not None:
        sql += f" AND {owner}.{identity}<?"
        args.append(before_id)
    if exact_id is not None:
        sql += f" AND {owner}.{identity}=?"
        args.append(exact_id)
    sql += f" ORDER BY {owner}.{identity} DESC LIMIT ?"
    result = []
    for row in connection.execute(sql, (*args, limit)).fetchall():
        try:
            if kind == "FILL":
                raw = json.loads(row["fill_json"])
                value = {"kind": kind, "id": str(row["fill_id"]), "fillId": str(row["fill_id"]),
                    "eventTimeMs": raw["event_time_ms"], "sourceSequence": raw["source_sequence"],
                    "side": raw["side"], "quantity": raw["quantity"], "price": raw["price"]}
            else:
                value = {"kind": kind, "id": str(row["trade_id"]), "fillId": str(row["fill_id"]),
                    "eventTimeMs": row["exit_time_ms"], "sourceSequence": row["exit_source_sequence"],
                    "side": row["position_side"], "quantity": row["quantity"], "price": row["exit_price"]}
            if not _valid(value) or value["eventTimeMs"] > context["virtualTimeMs"]:
                raise ValueError
            result.append(value)
        except (TypeError, ValueError, KeyError, IndexError):
            raise _error("Committed annotation reference is unavailable", corrupt=True) from None
    return result


def options(connection: sqlite3.Connection, context: Mapping[str, object], *, kind: str,
            before_id: str | None, limit: int) -> dict[str, object]:
    if type(limit) is not int or not 1 <= limit <= 20 or (before_id is not None
            and (not isinstance(before_id, str) or not 1 <= len(before_id) <= 128)):
        raise _error("Invalid annotation reference page")
    rows = _rows(connection, context, kind, before_id=before_id, limit=limit + 1)
    return {"protocol": "replay.v3", "schema_version": "replay.note-links.v1", "context": dict(context),
            "kind": kind, "links": rows[:limit], "nextBeforeId": rows[limit - 1]["id"] if len(rows) > limit else None}


def freeze(connection: sqlite3.Connection, context: Mapping[str, object], fields: Mapping[str, str]) -> list[dict[str, object]]:
    selected = []
    for kind, field in LINK_FIELDS.items():
        try:
            identifiers = json.loads(fields.get(field, "[]"))
            if not isinstance(identifiers, list) or len(identifiers) > MAX_LINKS or any(
                not isinstance(value, str) or not 1 <= len(value) <= 128 for value in identifiers
            ) or len(set(identifiers)) != len(identifiers):
                raise ValueError
        except (TypeError, ValueError):
            raise _error("Invalid annotation reference selection") from None
        for identifier in identifiers:
            rows = _rows(connection, context, kind, exact_id=identifier, limit=1)
            if not rows:
                raise _error("Reference is not visible in this run, track and event")
            selected.append(rows[0])
    if len(selected) > MAX_LINKS:
        raise _error("An annotation version may link at most eight fills or trades")
    return selected


def load(connection: sqlite3.Connection, run_id: str, note_id: str, revision: int) -> list[dict[str, object]]:
    row = connection.execute("SELECT links_json FROM replay_training_note_links WHERE run_id=? AND note_id=? AND revision=?",
                             (run_id, note_id, revision)).fetchone()
    try:
        value = json.loads(row[0])
        if not isinstance(value, list) or len(value) > MAX_LINKS or any(not _valid(link) for link in value) or len({(link["kind"], link["id"]) for link in value}) != len(value):
            raise ValueError
        return value
    except (TypeError, ValueError, IndexError):
        raise _error("Annotation reference version is unavailable", corrupt=True) from None
