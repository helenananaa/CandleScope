"""Versioned report storage; the public report and its digest stay unchanged."""
import json
import sqlite3

from .errors import BacktestError
from .identity import canonical_json, sha256_hex

STORAGE = "backtest.report-parts/1"
SECTIONS = ("fills", "orders", "trades", "rejected_orders", "order_events", "equity_curve", "ledger.order_events")


def at(report, path):
    current = report
    for key in path.split("."):
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def assign(report, path, value):
    keys = path.split(".")
    current = report
    for key in keys[:-1]:
        current[key] = dict(current[key])
        current = current[key]
    current[keys[-1]] = value


def encode_storage(report, *, part_limit, total_limit):
    head, sections, chunks = dict(report), {}, {}
    total = 0
    def chunk(rows, refs):
        nonlocal total
        raw = canonical_json(rows)
        size = len(raw.encode("utf-8"))
        if size > part_limit:
            if len(rows) < 2:
                raise BacktestError("BUDGET_EXCEEDED", "one report row exceeds the part byte limit")
            middle = len(rows) // 2
            chunk(rows[:middle], refs)
            chunk(rows[middle:], refs)
            return
        total += size
        if total > total_limit:
            raise BacktestError("BUDGET_EXCEEDED", "report exceeds configured storage byte limit")
        digest = "sha256:" + sha256_hex(raw)
        chunks[digest] = raw
        refs.append({"hash": digest, "count": len(rows)})
    for name in SECTIONS:
        rows = at(report, name)
        if not isinstance(rows, list) or not rows:
            continue
        refs = []
        for start in range(0, len(rows), 256):
            chunk(rows[start:start+256], refs)
        sections[name] = refs
        assign(head, name, [])
    manifest = {"storageSchema": STORAGE, "report": head, "sections": sections}
    manifest["manifestHash"] = "sha256:" + sha256_hex(manifest)
    raw = canonical_json(manifest)
    size = len(raw.encode("utf-8"))
    if size > part_limit or total + size > total_limit:
        raise BacktestError("BUDGET_EXCEEDED", "report summary exceeds configured byte limit")
    return raw, chunks


def manifest_from(row):
    value = json.loads(row["report_json"])
    if "storageSchema" not in value:
        return None, value
    if value["storageSchema"] != STORAGE:
        raise ValueError("unsupported report storage")
    digest = value.pop("manifestHash", None)
    if digest != "sha256:" + sha256_hex(value):
        raise ValueError("report manifest hash mismatch")
    if value["report"]["hashes"]["report"] != row["report_hash"]:
        raise ValueError("report identity hash mismatch")
    if value["report"]["runId"] != row["run_id"]:
        raise ValueError("report run identity mismatch")
    for name, refs in value["sections"].items():
        if name not in SECTIONS or at(value["report"], name) != [] or type(refs) is not list:
            raise ValueError("invalid report section")
        for ref in refs:
            if type(ref["count"]) is not int or not 1 <= ref["count"] <= 256 or type(ref["hash"]) is not str:
                raise ValueError("invalid report part reference")
    return value, value["report"]


def load_part(connection, run_id, ref):
    stored = connection.execute("SELECT payload_json FROM backtest_report_parts WHERE run_id=? AND part_hash=?",
                                (run_id, ref["hash"])).fetchone()
    if stored is None or "sha256:" + sha256_hex(stored[0]) != ref["hash"]:
        raise ValueError("report part missing or corrupt")
    rows = json.loads(stored[0])
    if type(rows) is not list or len(rows) != ref["count"]:
        raise ValueError("report part length mismatch")
    return rows


def read_report(row, connection, *, view="full", section=None, offset=0, limit=100):
    try:
        manifest, report = manifest_from(row)
        sections = manifest["sections"] if manifest else {}
        if view == "full":
            if manifest is None:
                return row
            for name, refs in sections.items():
                assign(report, name, [item for ref in refs for item in load_part(connection, row["run_id"], ref)])
            from .reports import verify_report_hash
            if not verify_report_hash(report):
                raise ValueError("expanded report hash mismatch")
            return {**row, "report_json": canonical_json(report)}
        if manifest is None:
            from .reports import verify_report_hash
            if not verify_report_hash(report) or report["hashes"]["report"] != row["report_hash"]:
                raise ValueError("inline report hash mismatch")
        counts = {name: sum(ref["count"] for ref in sections[name]) if name in sections
                  else len(at(report, name) or []) for name in SECTIONS}
        if view == "summary":
            head = dict(report)
            for name in SECTIONS:
                if at(head, name) is not None:
                    assign(head, name, [])
            return {"schemaVersion": "backtest.report-summary/1", "runId": row["run_id"],
                    "reportHash": row["report_hash"], "summary": head, "detailCounts": counts}
        if section not in SECTIONS or type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 500:
            raise BacktestError("SCHEMA_UNKNOWN_FIELD", "invalid report page request")
        rows, cursor = [], 0
        if section in sections:
            for ref in sections[section]:
                end = cursor + ref["count"]
                if end > offset and cursor < offset + limit:
                    part = load_part(connection, row["run_id"], ref)
                    rows.extend(part[max(0, offset-cursor):min(len(part), offset+limit-cursor)])
                cursor = end
                if cursor >= offset+limit:
                    break
        else:
            rows = (at(report, section) or [])[offset:offset+limit]
        return {"schemaVersion": "backtest.report-page/1", "runId": row["run_id"], "reportHash": row["report_hash"],
                "section": section, "offset": offset, "total": counts[section], "rows": rows,
                "nextOffset": offset+len(rows) if offset+len(rows) < counts[section] else None}
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise BacktestError("REPORT_CORRUPT", str(exc)) from exc


def publish_parts(connection, run_id, chunks):
    connection.execute("DELETE FROM backtest_report_parts WHERE run_id=?", (run_id,))
    for digest, raw in (chunks or {}).items():
        if "sha256:" + sha256_hex(raw) != digest:
            raise ValueError("report part hash mismatch")
        connection.execute("INSERT INTO backtest_report_parts VALUES (?, ?, ?)", (run_id, digest, raw))


def materialize_reports(connection):
    for row in connection.execute("SELECT * FROM backtest_reports").fetchall():
        full = read_report(dict(row), connection)
        connection.execute("UPDATE backtest_reports SET report_json=? WHERE run_id=?", (full["report_json"], full["run_id"]))
    connection.execute("DROP TABLE backtest_report_parts")


def rollback_reports(database):
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("BEGIN IMMEDIATE")
        if connection.execute("SELECT schema_version FROM backtest_schema_meta").fetchone()[0] != 9:
            raise RuntimeError("report rollback requires schema version 9")
        materialize_reports(connection)
        connection.execute("UPDATE backtest_schema_meta SET schema_version=8")
        connection.commit()
        return {"schemaVersion": 8, "reportsMaterialized": True}
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.close()
