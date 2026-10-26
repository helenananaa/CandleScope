"""Transport-independent facade for trading accounts and the trade journal."""
from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Protocol

from .journal import (
    field_timing,
    locked_plan,
    locked_risk,
    phase_at,
    plan_direction,
    plan_timing,
    risk_fields,
    should_coalesce,
    trade_metrics,
)
from .models import (
    ACCOUNT_KINDS,
    DEFAULT_PRACTICE_SETTINGS,
    ENTRY_KINDS,
    ORDER_TYPES,
    PLANNED_ACCOUNT_KINDS,
    SIDES,
    TradingAccountError,
    bounded_text,
    conflict,
    dec_str,
    invalid,
    new_id,
    normalize_fields,
    normalize_instrument,
    normalize_tags,
    not_found,
    now_ms,
    optional_decimal,
    to_decimal,
    valid_id,
)
from .practice import (
    BAR_MS,
    Cursor,
    PracticeMatcher,
    PracticeSettings,
    WorkingOrder,
    advance_cursor,
    reachable,
)
from .stats import TradeFacts, compute_stats, journal_tags
from .store import TradingStore
from .trades import Trade, build_trades, signed_position

ZERO = Decimal("0")
FRESH_PRICE_MS = 15_000
MAX_SNAPSHOT_IMAGE_BYTES = 6 * 1024 * 1024
MAX_SNAPSHOT_STATE_BYTES = 256 * 1024
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
SUGGESTION_LOOKBACK_MS = 24 * 3600 * 1000
# A cursor whose candle, extremes and status are unchanged is written back at
# most this often; only its last close and observation time are newer.
CURSOR_FLUSH_MS = 10_000


class MarketPort(Protocol):
    """Read-only candle access used for marks, cursor seeding and excursions."""

    def latest_bar(self, exchange: str, market_type: str, symbol: str) -> dict[str, Any] | None: ...

    def bars(
        self,
        exchange: str,
        market_type: str,
        symbol: str,
        interval: str,
        start_ms: int,
        end_ms: int | None,
        limit: int,
    ) -> tuple[list[dict[str, Any]], bool]: ...


Instrument = tuple[str, str, str]


def _instrument_of(row: dict[str, Any]) -> Instrument:
    return (row["exchange"], row["market_type"], row["symbol"])


def _fill_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "exchange": row["exchange"],
        "marketType": row["market_type"],
        "symbol": row["symbol"],
        "side": row["side"],
        "qty": dec_str(row["qty"]),
        "price": dec_str(row["price"]),
        "fee": dec_str(row["fee"]),
        "feeCurrency": row["fee_currency"],
        "liquidity": row["liquidity"],
        "orderId": row["order_id"],
        "tsMs": row["ts_ms"],
        "source": row["source"],
        "note": row["note"],
    }


def _order_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "accountId": row["account_id"],
        "exchange": row["exchange"],
        "marketType": row["market_type"],
        "symbol": row["symbol"],
        "side": row["side"],
        "type": row["type"],
        "qty": dec_str(row["qty"]),
        "limitPrice": dec_str(row["limit_price"]),
        "stopPrice": dec_str(row["stop_price"]),
        "reduceOnly": bool(row["reduce_only"]),
        "ocoGroup": row["oco_group"],
        "tag": row["tag"],
        "parentId": row["parent_id"],
        "bracketStop": dec_str(row["bracket_stop"]),
        "bracketTarget": dec_str(row["bracket_target"]),
        "status": row["status"],
        "createdAtMs": row["created_at_ms"],
        "updatedAtMs": row["updated_at_ms"],
        "fillPrice": dec_str(row["fill_price"]),
        "filledQty": dec_str(row["filled_qty"]),
        "filledAtMs": row["filled_at_ms"],
        "reason": row["reason"],
    }


def _working_order(row: dict[str, Any]) -> WorkingOrder:
    return WorkingOrder(
        id=row["id"],
        side=row["side"],
        type=row["type"],
        qty=row["qty"],
        created_at_ms=int(row["created_at_ms"]),
        limit_price=row["limit_price"],
        stop_price=row["stop_price"],
        reduce_only=bool(row["reduce_only"]),
        oco_group=row["oco_group"],
        tag=row["tag"],
        bracket_stop=row["bracket_stop"],
        bracket_target=row["bracket_target"],
        parent_id=row["parent_id"],
    )


def _cursor_from_row(row: dict[str, Any]) -> Cursor:
    return Cursor(
        bar_time=int(row["bar_time"]),
        seen_high=row["seen_high"],
        seen_low=row["seen_low"],
        last_close=row["last_close"],
        observed_ms=int(row["observed_ms"]),
        closes_only=bool(row["closes_only"]),
    )


def _cursor_key(cursor: Cursor, status: str, detail: str) -> tuple[Any, ...]:
    return (cursor.bar_time, cursor.seen_high, cursor.seen_low, cursor.closes_only, status, detail)


@dataclass(slots=True)
class _Feed:
    """In-memory practice cursor of one instrument; SQLite holds the last flush."""

    cursor: Cursor
    status: str
    detail: str
    flushed: tuple[Any, ...]
    flushed_at_ms: int
    flushed_cursor: Cursor
    # Last measured matcher step: live update -> applied (see practice_runtime).
    timing: dict[str, int] = field(default_factory=dict)


def _bar_decimal(bar: dict[str, Any], key: str) -> Decimal:
    value = bar[key]
    if isinstance(value, Decimal):
        return value
    return Decimal(repr(value) if isinstance(value, float) else str(value))


class TradingAccountService:
    def __init__(
        self,
        store: TradingStore,
        *,
        snapshot_dir: Path,
        market: MarketPort | None = None,
        clock: Callable[[], int] = now_ms,
        id_factory: Callable[[str], str] = new_id,
    ) -> None:
        self.store = store
        self.snapshot_dir = Path(snapshot_dir)
        self.market = market
        self.clock = clock
        self.new_id = id_factory
        self._feeds: dict[Instrument, _Feed] = {}

    # ══════════════════════════════════════════════════════════
    #  Accounts
    # ══════════════════════════════════════════════════════════

    def _account(self, account_id: str) -> dict[str, Any]:
        account = self.store.account(account_id) if valid_id(account_id) else None
        if account is None:
            raise not_found("Account")
        return account

    @staticmethod
    def _practice_settings(raw: Any, *, base: dict[str, str] | None = None) -> dict[str, str]:
        source = dict(base or DEFAULT_PRACTICE_SETTINGS)
        if raw is not None:
            if not isinstance(raw, dict):
                raise invalid("settings must be an object")
            for key in DEFAULT_PRACTICE_SETTINGS:
                if key in raw and raw[key] is not None:
                    source[key] = raw[key]
        initial = to_decimal(source["initialBalance"], "initialBalance", positive=True)
        taker = to_decimal(source["takerFeeRate"], "takerFeeRate")
        maker = to_decimal(source["makerFeeRate"], "makerFeeRate")
        slippage = to_decimal(source["slippageBps"], "slippageBps")
        leverage = to_decimal(source["leverage"], "leverage", positive=True)
        if not (ZERO <= taker <= Decimal("0.01") and ZERO <= maker <= Decimal("0.01")):
            raise invalid("fee rates must be between 0 and 0.01")
        if not ZERO <= slippage <= Decimal("100"):
            raise invalid("slippageBps must be between 0 and 100")
        if not Decimal("1") <= leverage <= Decimal("125"):
            raise invalid("leverage must be between 1 and 125")
        return {
            "initialBalance": dec_str(initial) or "0",
            "takerFeeRate": dec_str(taker) or "0",
            "makerFeeRate": dec_str(maker) or "0",
            "slippageBps": dec_str(slippage) or "0",
            "leverage": dec_str(leverage) or "1",
        }

    def create_account(self, payload: dict[str, Any]) -> dict[str, Any]:
        kind = str(payload.get("kind") or "").strip()
        if kind in PLANNED_ACCOUNT_KINDS:
            raise conflict(
                "Exchange accounts are planned but not available yet",
                code="TRADING_ACCOUNT_KIND_PLANNED",
            )
        if kind not in ACCOUNT_KINDS:
            raise invalid("kind must be practice or manual")
        name = bounded_text(payload.get("name"), "name", maximum=80, required=True).strip()
        quote = bounded_text(payload.get("quoteCurrency") or "USDT", "quoteCurrency", maximum=12).strip().upper()
        settings = self._practice_settings(payload.get("settings")) if kind == "practice" else {}
        account_id = self.new_id("acc")
        created = self.clock()
        with self.store.transaction() as conn:
            self.store.insert(conn, "accounts", {
                "id": account_id,
                "kind": kind,
                "name": name,
                "quote_currency": quote,
                "settings_json": json.dumps(settings, sort_keys=True),
                "created_at_ms": created,
                "archived": 0,
            })
            if kind == "practice":
                self.store.insert(conn, "cash_flows", {
                    "id": self.new_id("cf"),
                    "account_id": account_id,
                    "kind": "initial",
                    "amount": settings["initialBalance"],
                    "ts_ms": created,
                    "note": "",
                })
        return self.account_view(self._account(account_id))

    def update_account(self, account_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        account = self._account(account_id)
        values: dict[str, Any] = {}
        if "name" in payload:
            values["name"] = bounded_text(payload.get("name"), "name", maximum=80, required=True).strip()
        if "archived" in payload:
            values["archived"] = 1 if payload.get("archived") else 0
        if "settings" in payload and account["kind"] == "practice":
            raw = payload.get("settings") or {}
            if isinstance(raw, dict) and "initialBalance" in raw:
                raw = {key: value for key, value in raw.items() if key != "initialBalance"}
            values["settings_json"] = json.dumps(
                self._practice_settings(raw, base=account["settings"]), sort_keys=True,
            )
        if values:
            with self.store.transaction() as conn:
                self.store.update(conn, "accounts", values, "id = ?", (account_id,))
        return self.account_view(self._account(account_id))

    def reset_practice(self, account_id: str) -> dict[str, Any]:
        """Start a new practice period: balance back to the initial amount."""
        account = self._account(account_id)
        if account["kind"] != "practice":
            raise conflict("Only practice accounts can be reset")
        trades = self._trades(account_id)
        if any(trade.status == "open" for trade in trades):
            raise conflict("Close open positions before resetting", code="TRADING_POSITION_OPEN")
        now = self.clock()
        balance = self._balance(account_id, trades)
        initial = Decimal(account["settings"]["initialBalance"])
        with self.store.transaction() as conn:
            for row in self.store.orders(account_id, status="working", limit=10_000):
                self.store.update(conn, "orders", {
                    "status": "cancelled", "reason": "account_reset", "updated_at_ms": now,
                }, "id = ?", (row["id"],))
            self.store.insert(conn, "cash_flows", {
                "id": self.new_id("cf"),
                "account_id": account_id,
                "kind": "reset",
                "amount": initial - balance,
                "ts_ms": now,
                "note": "",
            })
        return self.account_summary(account_id)

    def account_view(self, account: dict[str, Any]) -> dict[str, Any]:
        kind = account["kind"]
        return {
            "id": account["id"],
            "kind": kind,
            "name": account["name"],
            "quoteCurrency": account["quote_currency"],
            "settings": account["settings"],
            "createdAtMs": account["created_at_ms"],
            "archived": account["archived"],
            "capabilities": {
                "placeOrders": kind == "practice",
                "manualFills": kind == "manual",
                "sync": False,
            },
        }

    def list_accounts(self) -> dict[str, Any]:
        return {
            "accounts": [self.account_view(account) for account in self.store.accounts()],
            "kinds": list(ACCOUNT_KINDS),
            "plannedKinds": list(PLANNED_ACCOUNT_KINDS),
        }

    # ══════════════════════════════════════════════════════════
    #  Ledger projections
    # ══════════════════════════════════════════════════════════

    def _trades(self, account_id: str) -> list[Trade]:
        return build_trades(account_id, self.store.fills(account_id))

    def _balance(self, account_id: str, trades: list[Trade]) -> Decimal:
        cash = sum((row["amount"] for row in self.store.cash_flows(account_id)), ZERO)
        realized = sum((trade.realized_pnl - trade.fees for trade in trades), ZERO)
        return cash + realized

    def _mark(self, instrument: Instrument) -> tuple[Decimal | None, int | None, str]:
        feed = self._feed(instrument)
        cursor = feed.cursor if feed is not None else None
        now = self.clock()
        if cursor is not None and now - cursor.observed_ms <= FRESH_PRICE_MS:
            return cursor.last_close, cursor.observed_ms, "practice"
        if self.market is not None:
            try:
                bar = self.market.latest_bar(*instrument)
            except Exception:
                bar = None
            if bar is not None:
                return _bar_decimal(bar, "close"), int(bar["time"]) * 1000, "market"
        if cursor is not None:
            return cursor.last_close, cursor.observed_ms, "stale"
        return None, None, "none"

    def account_summary(self, account_id: str) -> dict[str, Any]:
        account = self._account(account_id)
        trades = self._trades(account_id)
        balance = self._balance(account_id, trades)
        leverage = Decimal(account["settings"].get("leverage", "1")) if account["kind"] == "practice" else Decimal(1)
        unrealized = ZERO
        used_margin = ZERO
        positions = []
        for trade in trades:
            if trade.status != "open":
                continue
            instrument = (trade.exchange, trade.market_type, trade.symbol)
            mark, mark_ms, mark_source = self._mark(instrument)
            value = trade.unrealized_pnl(mark)
            unrealized += value or ZERO
            price = mark if mark is not None else (trade.avg_entry_price or ZERO)
            effective_leverage = leverage if trade.market_type == "futures" else Decimal(1)
            used_margin += trade.open_qty * price / effective_leverage
            view = trade.to_dict(mark=mark)
            view["markAtMs"] = mark_ms
            view["markSource"] = mark_source
            positions.append(view)
        equity = balance + unrealized
        working = [_order_view(row) for row in self.store.orders(account_id, status="working", limit=500)]
        instruments = sorted({(row["exchange"], row["marketType"], row["symbol"]) for row in working})
        feeds = []
        for instrument in instruments:
            feed = self._feed(instrument)
            feeds.append({
                "exchange": instrument[0],
                "marketType": instrument[1],
                "symbol": instrument[2],
                "status": feed.status if feed else "waiting",
                "detail": feed.detail if feed else "",
                "observedMs": feed.cursor.observed_ms if feed else None,
                "lastPrice": dec_str(feed.cursor.last_close) if feed else None,
                "lagMs": feed.timing.get("lagMs") if feed else None,
                "timing": dict(feed.timing) if feed and feed.timing else None,
            })
        return {
            "account": self.account_view(account),
            "balance": dec_str(balance),
            "equity": dec_str(equity),
            "unrealizedPnl": dec_str(unrealized),
            "usedMargin": dec_str(used_margin),
            "available": dec_str(equity - used_margin),
            "positions": positions,
            "workingOrders": working,
            "feeds": feeds,
            "closedTrades": sum(1 for trade in trades if trade.status == "closed"),
        }

    # ══════════════════════════════════════════════════════════
    #  Trades
    # ══════════════════════════════════════════════════════════

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

    def list_trades(self, account_id: str, *, status: str | None = None, limit: int = 200) -> dict[str, Any]:
        self._account(account_id)
        trades = self._trades(account_id)
        by_trade, _ = self._entries_by_trade(account_id)
        linked_ids = [entry["id"] for items in by_trade.values() for entry in items]
        revisions = self.store.revisions_for(linked_ids)
        selected = [trade for trade in reversed(trades) if status in (None, "", trade.status)][:limit]
        out = []
        for trade in selected:
            entries = by_trade.get(trade.id, [])
            note, plan = self._trade_note_and_plan(trade, entries, revisions)
            latest_fields = revisions[note["id"]][-1]["fields"] if note and revisions.get(note["id"]) else {}
            reviewed = any(latest_fields.get(key) for key in ("goodDecisions", "errors", "hypotheses", "adherence"))
            mark = None
            if trade.status == "open":
                mark = self._mark((trade.exchange, trade.market_type, trade.symbol))[0]
            view = trade.to_dict(mark=mark)
            view.update({
                "noteId": note["id"] if note else None,
                "entryCount": len(entries),
                "needsReview": trade.status == "closed" and not reviewed,
                "plan": plan,
                "metrics": trade_metrics(trade, plan),
            })
            out.append(view)
        return {"trades": out}

    def account_stats(
        self,
        account_id: str,
        *,
        from_ms: int | None = None,
        to_ms: int | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Closed-trade statistics of one account; the period filters on close time."""
        account = self._account(account_id)
        if from_ms is not None and to_ms is not None and from_ms >= to_ms:
            raise invalid("from must be before to")
        wanted = normalize_tags(tags)
        trades = self._trades(account_id)
        closed = [
            trade for trade in trades
            if trade.closed_at_ms is not None
            and (from_ms is None or trade.closed_at_ms >= from_ms)
            and (to_ms is None or trade.closed_at_ms < to_ms)
        ]
        by_trade, _ = self._entries_by_trade(account_id)
        revisions = self.store.revisions_for(
            [entry["id"] for trade in closed for entry in by_trade.get(trade.id, [])]
        )
        facts = []
        for trade in closed:
            entries = by_trade.get(trade.id, [])
            note, plan = self._trade_note_and_plan(trade, entries, revisions)
            note_revisions = revisions.get(note["id"], []) if note else []
            latest = note_revisions[-1]["fields"] if note_revisions else {}
            facts.append(TradeFacts(
                trade=trade,
                risk=locked_risk(plan),
                tags=journal_tags(entries, latest),
                plan_timing=plan_timing(field_timing(note_revisions, trade)),
            ))
        if wanted:
            facts = [row for row in facts if all(tag in row.tags for tag in wanted)]
        return {
            "accountId": account_id,
            "accountKind": account["kind"],
            "quoteCurrency": account["quote_currency"],
            "filters": {"fromMs": from_ms, "toMs": to_ms, "tags": wanted},
            "openTrades": sum(1 for trade in trades if trade.status == "open"),
            **compute_stats(facts),
        }

    def _trade(self, account_id: str, trade_id: str) -> Trade:
        for trade in self._trades(account_id):
            if trade.id == trade_id:
                return trade
        raise not_found("Trade")

    def trade_detail(self, account_id: str, trade_id: str) -> dict[str, Any]:
        self._account(account_id)
        trades = self._trades(account_id)
        trade = next((item for item in trades if item.id == trade_id), None)
        if trade is None:
            raise not_found("Trade")
        by_trade, all_entries = self._entries_by_trade(account_id)
        entries = by_trade.get(trade.id, [])
        revisions = self.store.revisions_for([entry["id"] for entry in entries])
        note, plan = self._trade_note_and_plan(trade, entries, revisions)
        mark = None
        if trade.status == "open":
            mark = self._mark((trade.exchange, trade.market_type, trade.symbol))[0]
        upper = trade.closed_at_ms or self.clock()
        candidates = [
            entry
            for entry in all_entries
            if entry["trade_id"] is None
            and entry["kind"] == "note"
            and _instrument_of(entry) == (trade.exchange, trade.market_type, trade.symbol)
            and trade.opened_at_ms - SUGGESTION_LOOKBACK_MS <= entry["created_at_ms"] <= upper
        ]
        candidate_revisions = self.store.revisions_for([entry["id"] for entry in candidates])
        suggestions = [
            self._link_suggestion(entry, candidate_revisions.get(entry["id"], []))
            for entry in candidates
        ]
        view = trade.to_dict(mark=mark)
        view.update({
            "noteId": note["id"] if note else None,
            "plan": plan,
            "metrics": trade_metrics(trade, plan),
            "entries": [
                self._entry_view(entry, revisions.get(entry["id"], []), trade)
                for entry in sorted(entries, key=lambda item: item["created_at_ms"])
            ],
            "linkSuggestions": suggestions,
        })
        return view

    def trade_excursion(self, account_id: str, trade_id: str) -> dict[str, Any]:
        """MFE/MAE from candles over the holding period (an estimate)."""
        trade = self._trade(account_id, trade_id)
        if self.market is None:
            raise TradingAccountError("TRADING_MARKET_UNAVAILABLE", "Market data is unavailable", status=503)
        end = trade.closed_at_ms or self.clock()
        duration = max(0, end - trade.opened_at_ms)
        interval, step = ("1m", 60_000) if duration <= 2 * 86_400_000 else (
            ("15m", 900_000) if duration <= 30 * 86_400_000 else ("1h", 3_600_000)
        )
        start = trade.opened_at_ms - trade.opened_at_ms % step
        bars, complete = self.market.bars(
            trade.exchange, trade.market_type, trade.symbol, interval, start, end, 5_000,
        )
        avg = trade.avg_entry_price
        if not bars or avg is None:
            return {"available": False, "interval": interval, "complete": complete}
        high = max(_bar_decimal(bar, "high") for bar in bars)
        low = min(_bar_decimal(bar, "low") for bar in bars)
        favorable = (high - avg) if trade.direction == "long" else (avg - low)
        adverse = (avg - low) if trade.direction == "long" else (high - avg)
        favorable = max(favorable, ZERO)
        adverse = max(adverse, ZERO)
        by_trade, _ = self._entries_by_trade(account_id)
        entries = by_trade.get(trade.id, [])
        revisions = self.store.revisions_for([entry["id"] for entry in entries])
        _, plan = self._trade_note_and_plan(trade, entries, revisions)
        risk = Decimal(plan["riskUsdt"]) if plan and plan.get("riskUsdt") else None
        to_r = (lambda value: dec_str((value * trade.max_qty / risk).quantize(Decimal("0.01")))) \
            if risk and risk > 0 else (lambda value: None)
        return {
            "available": True,
            "interval": interval,
            "complete": complete,
            "bars": len(bars),
            "mfePrice": dec_str(favorable),
            "maePrice": dec_str(adverse),
            "mfePct": dec_str((favorable / avg * 100).quantize(Decimal("0.01"))),
            "maePct": dec_str((adverse / avg * 100).quantize(Decimal("0.01"))),
            "mfeR": to_r(favorable),
            "maeR": to_r(adverse),
        }

    # ══════════════════════════════════════════════════════════
    #  Practice orders
    # ══════════════════════════════════════════════════════════

    def _settings(self, account: dict[str, Any], market_type: str) -> PracticeSettings:
        settings = account["settings"]
        return PracticeSettings(
            taker_fee_rate=Decimal(settings["takerFeeRate"]),
            maker_fee_rate=Decimal(settings["makerFeeRate"]),
            slippage_bps=Decimal(settings["slippageBps"]),
            allow_short=market_type == "futures",
        )

    def _reference_price(self, instrument: Instrument, client_price: Decimal | None) -> tuple[Decimal, str]:
        now = self.clock()
        feed = self._feed(instrument)
        if feed is not None and now - feed.cursor.observed_ms <= FRESH_PRICE_MS:
            return feed.cursor.last_close, "practice_feed"
        if self.market is not None:
            try:
                bar = self.market.latest_bar(*instrument)
            except Exception:
                bar = None
            if bar is not None and now - int(bar["time"]) * 1000 <= 2 * BAR_MS:
                return _bar_decimal(bar, "close"), "market_feed"
        if client_price is not None and client_price > 0:
            return client_price, "chart"
        raise TradingAccountError(
            "TRADING_NO_PRICE",
            "No current price is available for this market yet",
            status=409,
        )

    def _seed_cursor(self, conn, instrument: Instrument, price: Decimal, now: int) -> None:
        bar = None
        if self.market is not None:
            try:
                bar = self.market.latest_bar(*instrument)
            except Exception:
                bar = None
        minute = now // BAR_MS * 60
        if bar is not None and int(bar["time"]) == minute:
            values = {
                "bar_time": minute,
                "seen_high": max(_bar_decimal(bar, "high"), price),
                "seen_low": min(_bar_decimal(bar, "low"), price),
                "last_close": price,
                "closes_only": 0,
            }
        else:
            values = {
                "bar_time": minute,
                "seen_high": price,
                "seen_low": price,
                "last_close": price,
                "closes_only": 1,
            }
        self.store.upsert_cursor(conn, {
            "exchange": instrument[0],
            "market_type": instrument[1],
            "symbol": instrument[2],
            **values,
            "observed_ms": now,
            "status": "live",
            "detail": "",
            "updated_at_ms": now,
        })

    def place_order(self, account_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        # Serialize with the matcher so position and margin checks see the
        # same ledger the order is written against.
        with self.store.locked():
            return self._place_order(account_id, payload)

    def _place_order(self, account_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        account = self._account(account_id)
        if account["kind"] != "practice":
            raise conflict("This account cannot place orders", code="TRADING_ORDERS_UNSUPPORTED")
        if account["archived"]:
            raise conflict("Archived accounts cannot place orders")
        instrument = normalize_instrument(payload.get("exchange"), payload.get("marketType"), payload.get("symbol"))
        side = str(payload.get("side") or "").lower()
        order_type = str(payload.get("type") or "").lower()
        if side not in SIDES:
            raise invalid("side must be buy or sell")
        if order_type not in ORDER_TYPES:
            raise invalid("type must be market, limit or stop")
        qty = to_decimal(payload.get("qty"), "qty", positive=True)
        limit_price = optional_decimal(payload.get("limitPrice"), "limitPrice", positive=True)
        stop_price = optional_decimal(payload.get("stopPrice"), "stopPrice", positive=True)
        bracket_stop = optional_decimal(payload.get("bracketStop"), "bracketStop", positive=True)
        bracket_target = optional_decimal(payload.get("bracketTarget"), "bracketTarget", positive=True)
        reduce_only = bool(payload.get("reduceOnly"))
        client_price = optional_decimal(payload.get("referencePrice"), "referencePrice", positive=True)
        if order_type == "limit" and limit_price is None:
            raise invalid("limitPrice is required for limit orders")
        if order_type == "stop" and stop_price is None:
            raise invalid("stopPrice is required for stop orders")
        if reduce_only and (bracket_stop is not None or bracket_target is not None):
            raise invalid("reduce-only orders cannot carry a bracket")

        now = self.clock()
        reference, price_source = self._reference_price(instrument, client_price)
        trades = self._trades(account_id)
        position = signed_position(trades, *instrument)
        settings = self._settings(account, instrument[1])
        direction = Decimal(1) if side == "buy" else Decimal(-1)

        if order_type == "stop":
            assert stop_price is not None
            if (side == "buy" and stop_price <= reference) or (side == "sell" and stop_price >= reference):
                raise invalid("Stop price would trigger immediately", code="TRADING_STOP_WOULD_TRIGGER")
        entry_price = {"market": reference, "limit": limit_price, "stop": stop_price}[order_type] or reference
        if bracket_stop is not None and (bracket_stop - entry_price) * direction >= 0:
            raise invalid("Stop-loss must be on the losing side of the entry", code="TRADING_BRACKET_INVALID")
        if bracket_target is not None and (bracket_target - entry_price) * direction <= 0:
            raise invalid("Take-profit must be on the winning side of the entry", code="TRADING_BRACKET_INVALID")
        if reduce_only and (position == 0 or (position > 0) == (direction > 0)):
            raise conflict("There is no position to reduce", code="TRADING_NOTHING_TO_REDUCE")
        if not reduce_only and not settings.allow_short and side == "sell" and position - qty < 0:
            raise conflict("Spot practice cannot sell more than you hold", code="TRADING_INSUFFICIENT_POSITION")
        increases = not reduce_only and (position == 0 or (position > 0) == (direction > 0))
        if increases:
            summary = self.account_summary(account_id)
            leverage = Decimal(account["settings"]["leverage"]) if instrument[1] == "futures" else Decimal(1)
            required = qty * entry_price / leverage
            available = Decimal(summary["available"])
            if required > available:
                raise conflict(
                    f"Not enough available balance (needs {dec_str(required)}, available {dec_str(available)})",
                    code="TRADING_INSUFFICIENT_BALANCE",
                )

        order_id = self.new_id("ord")
        row = {
            "id": order_id,
            "account_id": account_id,
            "exchange": instrument[0],
            "market_type": instrument[1],
            "symbol": instrument[2],
            "side": side,
            "type": order_type,
            "qty": qty,
            "limit_price": limit_price,
            "stop_price": stop_price,
            "reduce_only": int(reduce_only),
            "oco_group": None,
            "tag": "exit" if reduce_only else "entry",
            "parent_id": None,
            "bracket_stop": bracket_stop,
            "bracket_target": bracket_target,
            "status": "working",
            "created_at_ms": now,
            "updated_at_ms": now,
        }
        marketable = order_type == "market" or (
            order_type == "limit" and limit_price is not None
            and ((side == "buy" and limit_price >= reference) or (side == "sell" and limit_price <= reference))
        )
        working_rows = self.store.working_orders_for(*instrument)
        with self.store.transaction() as conn:
            if not working_rows:
                self._seed_cursor(conn, instrument, reference, now)
            self.store.insert(conn, "orders", row)
            if marketable:
                # A marketable order fills now against the reference price.
                # Other working orders join the session so a fill that closes
                # the position also retires its reduce-only exits.
                order = _working_order(row)
                siblings = [
                    _working_order(item) for item in working_rows if item["account_id"] == account_id
                ]
                matcher = PracticeMatcher(
                    [*siblings, order], position, settings,
                    new_order_id=lambda: self.new_id("ord"),
                )
                matcher.execute(order, reference, now, liquidity="taker")
                self._persist_match(conn, account, instrument, matcher, now)
        if not working_rows:
            # Reload the freshly seeded cursor on next use.
            self._feeds.pop(instrument, None)
        stored = self.store.order(order_id)
        assert stored is not None
        return {"order": _order_view(stored), "priceSource": price_source, "referencePrice": dec_str(reference)}

    def cancel_order(self, account_id: str, order_id: str) -> dict[str, Any]:
        with self.store.locked():
            return self._cancel_order(account_id, order_id)

    def _cancel_order(self, account_id: str, order_id: str) -> dict[str, Any]:
        self._account(account_id)
        row = self.store.order(order_id) if valid_id(order_id) else None
        if row is None or row["account_id"] != account_id:
            raise not_found("Order")
        if row["status"] != "working":
            raise conflict("Order is no longer working", code="TRADING_ORDER_NOT_WORKING")
        now = self.clock()
        with self.store.transaction() as conn:
            self.store.update(conn, "orders", {
                "status": "cancelled", "reason": "user_cancelled", "updated_at_ms": now,
            }, "id = ? AND status = 'working'", (order_id,))
        stored = self.store.order(order_id)
        assert stored is not None
        return {"order": _order_view(stored)}

    def list_orders(self, account_id: str, *, status: str | None = None) -> dict[str, Any]:
        self._account(account_id)
        return {"orders": [_order_view(row) for row in self.store.orders(account_id, status=status)]}

    def _persist_match(
        self,
        conn,
        account: dict[str, Any],
        instrument: Instrument,
        matcher: PracticeMatcher,
        now: int,
    ) -> None:
        result = matcher.result
        for child in result.created:
            self.store.insert(conn, "orders", {
                "id": child.id,
                "account_id": account["id"],
                "exchange": instrument[0],
                "market_type": instrument[1],
                "symbol": instrument[2],
                "side": child.side,
                "type": child.type,
                "qty": child.qty,
                "limit_price": child.limit_price,
                "stop_price": child.stop_price,
                "reduce_only": int(child.reduce_only),
                "oco_group": child.oco_group,
                "tag": child.tag,
                "parent_id": child.parent_id,
                "bracket_stop": None,
                "bracket_target": None,
                "status": "working",
                "created_at_ms": child.created_at_ms,
                "updated_at_ms": now,
            })
        for fill in result.fills:
            self.store.insert(conn, "fills", {
                "id": self.new_id("fil"),
                "account_id": account["id"],
                "exchange": instrument[0],
                "market_type": instrument[1],
                "symbol": instrument[2],
                "side": fill.side,
                "qty": fill.qty,
                "price": fill.price,
                "fee": fill.fee,
                "fee_currency": account["quote_currency"],
                "liquidity": fill.liquidity,
                "order_id": fill.order_id,
                "ts_ms": fill.ts_ms,
                "source": "practice",
                "created_at_ms": now,
                "note": "",
            })
        for order_id, (price, ts_ms, qty) in result.filled.items():
            self.store.update(conn, "orders", {
                "status": "filled",
                "fill_price": price,
                "filled_qty": qty,
                "filled_at_ms": ts_ms,
                "updated_at_ms": now,
            }, "id = ?", (order_id,))
        for order_id, reason in result.cancelled.items():
            self.store.update(conn, "orders", {
                "status": "cancelled", "reason": reason, "updated_at_ms": now,
            }, "id = ? AND status = 'working'", (order_id,))

    # ── practice feeds ──────────────────────────────────────────
    # The matcher advances a cursor per instrument several times a second.
    # It lives in memory; SQLite is written when the candle, its extremes or
    # the status change, when orders fill, and otherwise every
    # CURSOR_FLUSH_MS. Losing the unflushed tail on a crash only replays a
    # path that produced no fills (every fill is written with its cursor).

    def _feed(self, instrument: Instrument) -> _Feed | None:
        with self.store.locked():
            feed = self._feeds.get(instrument)
            if feed is None:
                row = self.store.cursor(*instrument)
                if row is None:
                    return None
                cursor = _cursor_from_row(row)
                feed = _Feed(
                    cursor=cursor,
                    status=row["status"],
                    detail=row["detail"],
                    flushed=_cursor_key(cursor, row["status"], row["detail"]),
                    flushed_at_ms=int(row["updated_at_ms"]),
                    flushed_cursor=cursor,
                )
                self._feeds[instrument] = feed
            return feed

    def _write_feed(self, conn, instrument: Instrument, cursor: Cursor, status: str, detail: str, now: int) -> None:
        self.store.upsert_cursor(conn, {
            "exchange": instrument[0],
            "market_type": instrument[1],
            "symbol": instrument[2],
            "bar_time": cursor.bar_time,
            "seen_high": cursor.seen_high,
            "seen_low": cursor.seen_low,
            "last_close": cursor.last_close,
            "closes_only": int(cursor.closes_only),
            "observed_ms": cursor.observed_ms,
            "status": status,
            "detail": detail,
            "updated_at_ms": now,
        })

    @staticmethod
    def _mark_flushed(feed: _Feed, cursor: Cursor, status: str, detail: str, now: int) -> None:
        feed.cursor, feed.status, feed.detail = cursor, status, detail
        feed.flushed = _cursor_key(cursor, status, detail)
        feed.flushed_at_ms = now
        feed.flushed_cursor = cursor

    def apply_market_bars(
        self,
        instrument: Instrument,
        bars: list[dict[str, Any]],
        *,
        observed_ms: int,
        status: str = "live",
        detail: str = "",
    ) -> int:
        """Replay candles for one instrument through every practice account.

        ``bars`` are 1m candles in ascending time starting at or after the
        cursor; the caller guarantees there is no gap. Returns the fill count.
        """
        detail = detail[:500]
        with self.store.locked():
            feed = self._feed(instrument)
            if feed is None:
                return 0
            cursor = feed.cursor
            chunks = []
            for bar in bars:
                bar_time = int(bar["time"])
                bar_end_ms = bar_time * 1000 + BAR_MS - 1
                cursor, chunk = advance_cursor(
                    cursor,
                    bar_time,
                    _bar_decimal(bar, "open"),
                    _bar_decimal(bar, "high"),
                    _bar_decimal(bar, "low"),
                    _bar_decimal(bar, "close"),
                    observed_ms=min(observed_ms, bar_end_ms),
                )
                if chunk is not None and len(chunk.points) > 1:
                    chunks.append(chunk)
            if bars:
                cursor = replace(cursor, observed_ms=max(cursor.observed_ms, observed_ms))

            sessions: list[tuple[dict[str, Any], PracticeMatcher]] = []
            if chunks:
                low = min(min(chunk.points) for chunk in chunks)
                high = max(max(chunk.points) for chunk in chunks)
                rows = self.store.working_orders_for(*instrument)
                # Most updates move price nowhere near an order; skip loading
                # the ledgers unless one could trigger.
                if any(reachable(_working_order(row), low, high) for row in rows):
                    sessions = self._match_sessions(instrument, rows)
                for chunk in chunks:
                    for _, matcher in sessions:
                        matcher.run(chunk)

            now = self.clock()
            fills = sum(len(matcher.result.fills) for _, matcher in sessions)
            changed = any(
                matcher.result.fills or matcher.result.cancelled or matcher.result.created
                for _, matcher in sessions
            )
            due = cursor != feed.flushed_cursor and now - feed.flushed_at_ms >= CURSOR_FLUSH_MS
            if changed or due or _cursor_key(cursor, status, detail) != feed.flushed:
                with self.store.transaction() as conn:
                    for account, matcher in sessions:
                        self._persist_match(conn, account, instrument, matcher, now)
                    self._write_feed(conn, instrument, cursor, status, detail, now)
                self._mark_flushed(feed, cursor, status, detail, now)
            else:
                feed.cursor, feed.status, feed.detail = cursor, status, detail
            return fills

    def _match_sessions(
        self, instrument: Instrument, rows: list[dict[str, Any]],
    ) -> list[tuple[dict[str, Any], PracticeMatcher]]:
        by_account: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_account.setdefault(row["account_id"], []).append(row)
        sessions: list[tuple[dict[str, Any], PracticeMatcher]] = []
        for account_id, orders in by_account.items():
            account = self.store.account(account_id)
            if account is None or account["kind"] != "practice":
                continue
            position = signed_position(self._trades(account_id), *instrument)
            sessions.append((account, PracticeMatcher(
                [_working_order(row) for row in orders],
                position,
                self._settings(account, instrument[1]),
                new_order_id=lambda: self.new_id("ord"),
            )))
        return sessions

    def set_feed_status(self, instrument: Instrument, status: str, detail: str = "") -> None:
        detail = detail[:500]
        with self.store.locked():
            feed = self._feed(instrument)
            if feed is None:
                return
            if _cursor_key(feed.cursor, status, detail) == feed.flushed:
                feed.status, feed.detail = status, detail
                return
            now = self.clock()
            with self.store.transaction() as conn:
                self._write_feed(conn, instrument, feed.cursor, status, detail, now)
            self._mark_flushed(feed, feed.cursor, status, detail, now)

    def record_feed_timing(self, instrument: Instrument, timing: dict[str, int]) -> None:
        with self.store.locked():
            feed = self._feed(instrument)
            if feed is not None:
                feed.timing = dict(timing)

    def flush_feeds(self) -> None:
        """Write every cursor that changed since its last flush (shutdown)."""
        with self.store.locked():
            pending = [
                (instrument, feed) for instrument, feed in self._feeds.items()
                if feed.cursor != feed.flushed_cursor
            ]
            if not pending:
                return
            now = self.clock()
            with self.store.transaction() as conn:
                for instrument, feed in pending:
                    self._write_feed(conn, instrument, feed.cursor, feed.status, feed.detail, now)
            for _, feed in pending:
                self._mark_flushed(feed, feed.cursor, feed.status, feed.detail, now)

    def working_instruments(self) -> list[Instrument]:
        return self.store.working_instruments()

    def cursor_start_ms(self, instrument: Instrument) -> int | None:
        feed = self._feed(instrument)
        return feed.cursor.bar_time * 1000 if feed is not None else None

    # ══════════════════════════════════════════════════════════
    #  Manual fills
    # ══════════════════════════════════════════════════════════

    def add_fill(self, account_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        account = self._account(account_id)
        if account["kind"] != "manual":
            raise conflict("Fills can only be entered on manual accounts", code="TRADING_MANUAL_ONLY")
        instrument = normalize_instrument(payload.get("exchange"), payload.get("marketType"), payload.get("symbol"))
        side = str(payload.get("side") or "").lower()
        if side not in SIDES:
            raise invalid("side must be buy or sell")
        qty = to_decimal(payload.get("qty"), "qty", positive=True)
        price = to_decimal(payload.get("price"), "price", positive=True)
        fee = optional_decimal(payload.get("fee"), "fee") or ZERO
        if fee < 0:
            raise invalid("fee must not be negative")
        now = self.clock()
        ts = payload.get("tsMs")
        ts_ms = now if ts is None else int(to_decimal(ts, "tsMs", positive=True))
        if ts_ms > now + 60_000:
            raise invalid("fill time cannot be in the future")
        fill_id = self.new_id("fil")
        with self.store.transaction() as conn:
            self.store.insert(conn, "fills", {
                "id": fill_id,
                "account_id": account_id,
                "exchange": instrument[0],
                "market_type": instrument[1],
                "symbol": instrument[2],
                "side": side,
                "qty": qty,
                "price": price,
                "fee": fee,
                "fee_currency": account["quote_currency"],
                "liquidity": "manual",
                "order_id": None,
                "ts_ms": ts_ms,
                "source": "manual",
                "created_at_ms": now,
                "note": bounded_text(payload.get("note"), "note", maximum=500),
            })
        row = self.store.fill(fill_id)
        assert row is not None
        return {"fill": _fill_view(row)}

    def delete_fill(self, account_id: str, fill_id: str) -> dict[str, Any]:
        account = self._account(account_id)
        row = self.store.fill(fill_id) if valid_id(fill_id) else None
        if row is None or row["account_id"] != account_id:
            raise not_found("Fill")
        if account["kind"] != "manual" or row["source"] != "manual":
            raise conflict("Only manually entered fills can be deleted", code="TRADING_MANUAL_ONLY")
        with self.store.transaction() as conn:
            conn.execute("DELETE FROM fills WHERE id = ?", (fill_id,))
        return {"deleted": fill_id}

    def list_fills(self, account_id: str) -> dict[str, Any]:
        self._account(account_id)
        return {"fills": [_fill_view(row) for row in reversed(self.store.fills(account_id))]}

    # ══════════════════════════════════════════════════════════
    #  Journal
    # ══════════════════════════════════════════════════════════

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
        entry_id = self.new_id("je")
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
                "saved_at_ms": now,
                "fields_json": json.dumps(fields, sort_keys=True),
                "body": body,
            })
        return self.entry_detail(entry_id)

    def save_entry(self, entry_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        entry = self._entry(entry_id)
        revisions = self.store.revisions(entry_id)
        latest = revisions[-1] if revisions else None
        fields = normalize_fields(payload["fields"]) if "fields" in payload else (latest or {}).get("fields", {})
        body = bounded_text(payload.get("body"), "body") if "body" in payload else (latest or {}).get("body", "")
        now = self.clock()
        trade = self._trade_or_none(entry["account_id"], entry["trade_id"])
        fill_times = [] if trade is not None else [
            int(fill["ts_ms"])
            for fill in self.store.fills(entry["account_id"])
            if _instrument_of(fill) == _instrument_of(entry)
        ]
        values: dict[str, Any] = {"updated_at_ms": now}
        if "tags" in payload:
            values["tags_json"] = json.dumps(normalize_tags(payload.get("tags")))
        changed = latest is None or latest["fields"] != fields or latest["body"] != body
        with self.store.transaction() as conn:
            if changed:
                if should_coalesce(latest, now, trade, fill_times):
                    assert latest is not None
                    self.store.update(conn, "journal_revisions", {
                        "saved_at_ms": now,
                        "fields_json": json.dumps(fields, sort_keys=True),
                        "body": body,
                    }, "entry_id = ? AND revision = ?", (entry_id, latest["revision"]))
                else:
                    self.store.insert(conn, "journal_revisions", {
                        "entry_id": entry_id,
                        "revision": (latest["revision"] + 1) if latest else 1,
                        "saved_at_ms": now,
                        "fields_json": json.dumps(fields, sort_keys=True),
                        "body": body,
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
                {
                    "revision": rev["revision"],
                    "savedAtMs": rev["saved_at_ms"],
                    "fields": rev["fields"],
                    "body": rev["body"],
                }
                for rev in self.store.revisions(entry_id)
            ]
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
