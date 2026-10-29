"""Journal persistence shared by editable and read-only trade projections.

This service has no order, cash-flow or fill mutation API.
"""
from __future__ import annotations

import base64
import binascii
import json
from pathlib import Path
from typing import Any, Callable

from .journal import field_timing, locked_plan, phase_at, plan_direction, risk_fields
from .models import (ENTRY_KINDS, bounded_text, conflict, dec_str, invalid, new_id,
                     normalize_fields, normalize_instrument, normalize_tags, not_found,
                     now_ms, to_decimal, valid_id)
from .store import TradingStore
from .trades import Trade

MAX_SNAPSHOT_IMAGE_BYTES = 6 * 1024 * 1024
MAX_SNAPSHOT_STATE_BYTES = 256 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _instrument_of(row: dict[str, Any]) -> tuple[str, str, str]:
    return row["exchange"], row["market_type"], row["symbol"]


class JournalService:
    def __init__(self, store: TradingStore, *, snapshot_dir: Path,
                 clock: Callable[[], int] = now_ms,
                 id_factory: Callable[[str], str] = new_id) -> None:
        self.store = store
        self.snapshot_dir = Path(snapshot_dir)
        self.clock = clock
        self.new_id = id_factory

    def _account(self, account_id: str) -> dict[str, Any]:
        account = self.store.account(account_id) if valid_id(account_id) else None
        if account is None:
            raise not_found("Account")
        return account

    def _trades(self, account_id: str) -> list[Trade]:
        raise NotImplementedError

    def _entries_by_trade(self, account_id: str) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
        entries = self.store.entries(account_id, limit=5_000)
        by_trade: dict[str, list[dict[str, Any]]] = {}
        for entry in entries:
            if entry["trade_id"]:
                by_trade.setdefault(entry["trade_id"], []).append(entry)
        return by_trade, entries

    def _trade_note_and_plan(
        self,
        trade: Trade,
        entries: list[dict[str, Any]],
        revisions: dict[str, list[dict[str, Any]]],
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        notes = sorted(
            (entry for entry in entries if entry["kind"] == "note"),
            key=lambda entry: entry["created_at_ms"],
        )
        if not notes:
            return None, None
        note = notes[0]
        return note, locked_plan(revisions.get(note["id"], []), trade)

    def _entry(self, entry_id: str) -> dict[str, Any]:
        entry = self.store.entry(entry_id) if valid_id(entry_id) else None
        if entry is None:
            raise not_found("Journal entry")
        return entry

    def _trade_or_none(self, account_id: str, trade_id: str | None) -> Trade | None:
        if not trade_id:
            return None
        for trade in self._trades(account_id):
            if trade.id == trade_id:
                return trade
        return None

    @staticmethod
    def _entry_summary(entry: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": entry["id"],
            "kind": entry["kind"],
            "createdAtMs": entry["created_at_ms"],
            "symbol": entry["symbol"],
            "tradeId": entry["trade_id"],
        }

    @classmethod
    def _link_suggestion(cls, entry: dict[str, Any], revisions: list[dict[str, Any]]) -> dict[str, Any]:
        """Summary plus the plan's latest risk fields, so same-minute plans can be told apart."""
        plan = risk_fields(revisions[-1]["fields"] if revisions else {})
        return {
            **cls._entry_summary(entry),
            **{key: dec_str(value) for key, value in plan.items()},
            "direction": plan_direction(plan),
        }

    def _entry_view(
        self,
        entry: dict[str, Any],
        revisions: list[dict[str, Any]],
        trade: Trade | None,
        *,
        include_history: bool = False,
    ) -> dict[str, Any]:
        latest = revisions[-1] if revisions else {"fields": {}, "body": "", "saved_at_ms": entry["created_at_ms"]}
        created_phase = phase_at(int(entry["created_at_ms"]), trade)
        snapshots = self.store.snapshots(entry["id"])
        return {
            "id": entry["id"],
            "accountId": entry["account_id"],
            "exchange": entry["exchange"],
            "marketType": entry["market_type"],
            "symbol": entry["symbol"],
            "kind": entry["kind"],
            "tradeId": entry["trade_id"],
            "createdAtMs": entry["created_at_ms"],
            "updatedAtMs": entry["updated_at_ms"],
            "marketTimeMs": entry["market_time_ms"],
            "templateId": entry["template_id"],
            "templateVersion": entry["template_version"],
            "tags": entry["tags"],
            "fields": latest["fields"],
            "body": latest["body"],
            "revisionCount": len(revisions),
            **({"revisions": [self._revision_view(rev) for rev in revisions]} if include_history else {}),
            "stage": created_phase,
            "reviewNote": entry["market_time_ms"] is not None,
            "fieldTiming": field_timing(revisions, trade),
            "plan": locked_plan(revisions, trade) if entry["kind"] == "note" else None,
            "snapshots": [
                {
                    "id": snap["id"],
                    "createdAtMs": snap["created_at_ms"],
                    "hasImage": bool(snap["image_file"]),
                    "state": snap["state"],
                }
                for snap in snapshots
            ],
        }

    def entry_detail(self, entry_id: str) -> dict[str, Any]:
        entry = self._entry(entry_id)
        trade = self._trade_or_none(entry["account_id"], entry["trade_id"])
        return self._entry_view(entry, self.store.revisions(entry_id), trade)

    def list_entries(
        self,
        account_id: str,
        *,
        symbol: str | None = None,
        unlinked_only: bool = False,
    ) -> dict[str, Any]:
        self._account(account_id)
        trades = {trade.id: trade for trade in self._trades(account_id)}
        entries = self.store.entries(account_id)
        if symbol:
            symbol = symbol.strip().upper()
            entries = [entry for entry in entries if entry["symbol"] == symbol]
        if unlinked_only:
            entries = [entry for entry in entries if not entry["trade_id"]]
        revisions = self.store.revisions_for([entry["id"] for entry in entries])
        return {
            "entries": [
                self._entry_view(entry, revisions.get(entry["id"], []), trades.get(entry["trade_id"] or ""))
                for entry in entries
            ]
        }

    def create_entry(self, account_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self.store.locked():
            return self._create_entry(account_id, payload)

    def _create_entry(self, account_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._account(account_id)
        kind = str(payload.get("kind") or "note")
        if kind not in ENTRY_KINDS:
            raise invalid("kind must be note or quick")
        instrument = normalize_instrument(payload.get("exchange"), payload.get("marketType"), payload.get("symbol"))
        trade_id = payload.get("tradeId") or None
        if trade_id is not None:
            trade = self._trade_or_none(account_id, str(trade_id))
            if trade is None:
                raise not_found("Trade")
            if (trade.exchange, trade.market_type, trade.symbol) != instrument:
                raise invalid("entry market must match the trade")
        fields = normalize_fields(payload.get("fields"))
        body = bounded_text(payload.get("body"), "body")
        if kind == "quick" and not body.strip():
            raise invalid("quick notes need text")
        market_time = payload.get("marketTimeMs")
        market_time_ms = None if market_time is None else int(to_decimal(market_time, "marketTimeMs", positive=True))
        template_id = bounded_text(payload.get("templateId"), "templateId", maximum=64).strip() or None
        template_version = payload.get("templateVersion")
        template_version = int(template_version) if isinstance(template_version, int) else None
        now = self.clock()
        entry_id = payload.get("clientEntryId") or self.new_id("je")
        if not valid_id(entry_id) or not entry_id.startswith("je_") or entry_id.endswith("~r"):
            raise invalid("Invalid clientEntryId")
        previous = self.store.one("SELECT * FROM journal_entries WHERE id = ?", (entry_id,))
        if previous is not None:
            if (previous["deleted"] or previous["account_id"] != account_id
                    or _instrument_of(previous) != instrument or previous["kind"] != kind
                    or previous["trade_id"] != trade_id or previous["market_time_ms"] != market_time_ms):
                raise conflict("Journal creation identifier is already in use")
            return self.entry_detail(entry_id)
        with self.store.transaction() as conn:
            self.store.insert(conn, "journal_entries", {
                "id": entry_id,
                "account_id": account_id,
                "exchange": instrument[0],
                "market_type": instrument[1],
                "symbol": instrument[2],
                "kind": kind,
                "trade_id": trade_id,
                "created_at_ms": now,
                "updated_at_ms": now,
                "market_time_ms": market_time_ms,
                "template_id": template_id,
                "template_version": template_version,
                "tags_json": json.dumps(normalize_tags(payload.get("tags"))),
                "deleted": 0,
            })
            self.store.insert(conn, "journal_revisions", {
                "entry_id": entry_id,
                "revision": 1,
                "history_complete": 1,
                "saved_at_ms": now,
                "fields_json": json.dumps(fields, sort_keys=True),
                "body": body,
            })
        return self.entry_detail(entry_id)

    def save_entry(self, entry_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self.store.locked():
            return self._save_entry(entry_id, payload)

    def _save_entry(self, entry_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        entry = self._entry(entry_id)
        revisions = self.store.revisions(entry_id)
        latest = revisions[-1] if revisions else None
        fields = normalize_fields(payload["fields"]) if "fields" in payload else (latest or {}).get("fields", {})
        body = bounded_text(payload.get("body"), "body") if "body" in payload else (latest or {}).get("body", "")
        now = self.clock()
        expected = payload.get("expectedRevision")
        if expected is not None and (type(expected) is not int or expected < 1):
            raise invalid("expectedRevision must be a positive integer")
        changed = latest is None or latest["fields"] != fields or latest["body"] != body
        tags_changed = "tags" in payload and normalize_tags(payload["tags"]) != entry["tags"]
        if expected is not None and expected != (latest["revision"] if latest else 0):
            if changed or tags_changed:
                raise conflict("This note changed in another editor. Your local draft has been kept.",
                               "TRADING_JOURNAL_CONFLICT")
            return self.entry_detail(entry_id)  # retry after a lost successful response
        values: dict[str, Any] = {"updated_at_ms": now}
        if "tags" in payload:
            values["tags_json"] = json.dumps(normalize_tags(payload.get("tags")))
        with self.store.transaction() as conn:
            if changed or (latest and not latest["history_complete"]):
                self.store.insert(conn, "journal_revisions", {
                    "entry_id": entry_id,
                    "revision": (latest["revision"] + 1) if latest else 1,
                    "saved_at_ms": max(now, int(latest["saved_at_ms"])) if latest else now,
                    "fields_json": json.dumps(fields, sort_keys=True),
                    "body": body,
                    "history_complete": 1,
                })
            self.store.update(conn, "journal_entries", values, "id = ?", (entry_id,))
        return self.entry_detail(entry_id)

    def link_entry(self, entry_id: str, trade_id: str | None) -> dict[str, Any]:
        entry = self._entry(entry_id)
        if trade_id:
            trade = self._trade_or_none(entry["account_id"], trade_id)
            if trade is None:
                raise not_found("Trade")
            if (trade.exchange, trade.market_type, trade.symbol) != _instrument_of(entry):
                raise invalid("entry market must match the trade")
        with self.store.transaction() as conn:
            self.store.update(conn, "journal_entries", {
                "trade_id": trade_id or None, "updated_at_ms": self.clock(),
            }, "id = ?", (entry_id,))
        return self.entry_detail(entry_id)

    def delete_entry(self, entry_id: str) -> dict[str, Any]:
        self._entry(entry_id)
        with self.store.transaction() as conn:
            self.store.update(conn, "journal_entries", {
                "deleted": 1, "updated_at_ms": self.clock(),
            }, "id = ?", (entry_id,))
        return {"deleted": entry_id}

    def entry_revisions(self, entry_id: str) -> dict[str, Any]:
        self._entry(entry_id)
        return {
            "revisions": [
                self._revision_view(rev)
                for rev in self.store.revisions(entry_id)
            ]
        }

    @staticmethod
    def _revision_view(rev: dict[str, Any]) -> dict[str, Any]:
        return {
            "revision": rev["revision"], "savedAtMs": rev["saved_at_ms"],
            "fields": rev["fields"], "body": rev["body"],
            "historyComplete": bool(rev["history_complete"]),
        }

    # ── snapshots ───────────────────────────────────────────────

    def add_snapshot(self, entry_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._entry(entry_id)
        state = payload.get("state") or {}
        if not isinstance(state, dict):
            raise invalid("state must be an object")
        state_json = json.dumps(state, sort_keys=True)
        if len(state_json.encode("utf-8")) > MAX_SNAPSHOT_STATE_BYTES:
            raise invalid("snapshot state is too large")
        image = payload.get("image")
        image_bytes: bytes | None = None
        if image:
            text = str(image)
            prefix = "data:image/png;base64,"
            if text.startswith(prefix):
                text = text[len(prefix):]
            try:
                image_bytes = base64.b64decode(text, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise invalid("image must be base64 PNG") from exc
            if not image_bytes.startswith(PNG_SIGNATURE):
                raise invalid("image must be a PNG")
            if len(image_bytes) > MAX_SNAPSHOT_IMAGE_BYTES:
                raise invalid("image is too large")
        snapshot_id = self.new_id("snp")
        image_file = None
        if image_bytes is not None:
            self.snapshot_dir.mkdir(parents=True, exist_ok=True)
            image_file = f"{snapshot_id}.png"
            target = self.snapshot_dir / image_file
            temp = target.with_suffix(".tmp")
            temp.write_bytes(image_bytes)
            temp.replace(target)
        with self.store.transaction() as conn:
            self.store.insert(conn, "snapshots", {
                "id": snapshot_id,
                "entry_id": entry_id,
                "created_at_ms": self.clock(),
                "image_file": image_file,
                "state_json": state_json,
            })
        return self.entry_detail(entry_id)

    def snapshot_image_path(self, snapshot_id: str) -> Path:
        row = self.store.snapshot(snapshot_id) if valid_id(snapshot_id) else None
        if row is None or not row["image_file"]:
            raise not_found("Snapshot image")
        path = self.snapshot_dir / row["image_file"]
        if not path.is_file():
            raise not_found("Snapshot image")
        return path
