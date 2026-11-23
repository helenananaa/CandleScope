"""P6e1 practice account baselines for ADR-BACKTEST-015 (shared account model, O3).

P6e makes the practice account rules the account model forward runs share: one-way or hedge
positions, gross-notional margin, maker/taker fees and the candle fill path. Before that model
moves (P6e2) and enters the Host kernel (P6e3), these baselines pin what a practice account
does today, end to end through ``TradingAccountService``: orders placed, forming and closing
1m candles applied, then fills, orders (with cancel reasons), trades and the summary read back.

Regenerate deliberately, then review the JSON diff:

    CANDLESCOPE_UPDATE_STRATEGY_ORACLES=1 pytest tests/test_practice_baselines.py
"""
from __future__ import annotations

import json
import os
import re
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping

import pytest

from app.backtest.identity import canonical_json, sha256_hex
from app.trading_accounts.models import TradingAccountError
from app.trading_accounts.service import TradingAccountService
from app.trading_accounts.store import TradingStore
from tests.strategy_run_oracles import UPDATE_ENV, bars, scenario
from tests.test_trading_accounts import T0, Clock, FakeMarket

SCHEMA = "candlescope.practice-baseline/1"
GOLDEN_DIR = Path(__file__).resolve().parent / "fixtures" / "trading" / "practice_baselines"
SETTINGS = {"initialBalance": "1000", "leverage": "10", "takerFeeRate": "0.0005", "makerFeeRate": "0.0002",
            "slippageBps": "1"}
FORMING = (20_000, 40_000)  # each minute is seen forming twice before it closes
ID = re.compile(r"\b(?:acc|ord|fil|trd|ent|rev)_[0-9a-f]{20}\b")


def candles() -> list[dict[str, Any]]:
    """The P0 swing minutes, moved to a real minute boundary."""
    base = T0 // 1000
    return [{"time": base + index * 60, **{key: Decimal(str(bar.payload[key])) for key in ("open", "high", "low", "close")}}
            for index, bar in enumerate(bars())]


def _forming(candle: Mapping[str, Any], step: int) -> dict[str, Any]:
    """A partial view of ``candle``: half of each extreme, then the high, before the close."""
    open_, high, low, close = (candle[key] for key in ("open", "high", "low", "close"))
    seen_high = open_ + (high - open_) / 2 if step == 0 else high
    seen_low = open_ - (open_ - low) / 2
    last = (open_ + close) / 2
    return {"time": candle["time"], "open": open_, "high": max(seen_high, last), "low": min(seen_low, last), "close": last}


Script = Callable[[TradingAccountService, str, int, Mapping[str, Any]], None]


def _order(service: TradingAccountService, account: str, market: str, **fields: Any) -> dict[str, Any]:
    payload = {"exchange": "binance", "marketType": market, "symbol": "BTCUSDT",
               **{key: str(value) if isinstance(value, (Decimal, int, float)) else value for key, value in fields.items()}}
    return service.place_order(account, payload)


def one_way(service: TradingAccountService, account: str, index: int, last: Mapping[str, Any]) -> list[dict]:
    close = last["close"]
    plan = {
        2: dict(side="buy", type="market", qty=2, referencePrice=close, bracketStop=close - 3, bracketTarget=close + 4),
        9: dict(side="buy", type="limit", qty=1, limitPrice=last["low"] - 1, bracketStop=last["low"] - 5),
        14: dict(side="sell", type="stop", qty=1, stopPrice=close - 2, referencePrice=close),
        20: dict(side="sell", type="market", qty=3, referencePrice=close, bracketStop=close + 3, bracketTarget=close - 5),
        27: dict(side="buy", type="limit", qty=1, limitPrice=close - 2, reduceOnly=True),
        33: dict(side="buy", type="market", qty=120, referencePrice=close),  # beyond the account's margin
        36: dict(side="buy", type="stop", qty=1, stopPrice=close + 3, referencePrice=close, bracketTarget=close + 7),
    }
    return [plan[index]] if index in plan else []


def hedge(service: TradingAccountService, account: str, index: int, last: Mapping[str, Any]) -> list[dict]:
    close = last["close"]
    plan = {
        2: dict(positionSide="LONG", positionEffect="open", type="market", qty=2, referencePrice=close,
                bracketStop=close - 3, bracketTarget=close + 4),
        6: dict(positionSide="SHORT", positionEffect="open", type="market", qty=1, referencePrice=close,
                bracketStop=close + 3, bracketTarget=close - 5),
        12: dict(positionSide="LONG", positionEffect="open", type="limit", qty=1, limitPrice=last["low"] - 1),
        18: dict(positionSide="SHORT", positionEffect="open", type="stop", qty=2, stopPrice=close - 2, referencePrice=close),
        25: dict(positionSide="LONG", positionEffect="close", type="limit", qty=1, limitPrice=close + 2),
        31: dict(positionSide="SHORT", positionEffect="close", type="market", qty=1, referencePrice=close),
    }
    return [plan[index]] if index in plan else []


def spot(service: TradingAccountService, account: str, index: int, last: Mapping[str, Any]) -> list[dict]:
    close = last["close"]
    plan = {
        2: dict(side="buy", type="market", qty=3, referencePrice=close, bracketStop=close - 3),
        8: dict(side="sell", type="market", qty=5, referencePrice=close),  # more than held
        11: dict(side="buy", type="limit", qty=2, limitPrice=last["low"] - 1),
        17: dict(side="sell", type="limit", qty=1, limitPrice=close + 3),
        24: dict(side="sell", type="stop", qty=1, stopPrice=close - 2, referencePrice=close),
    }
    return [plan[index]] if index in plan else []


VARIANTS: dict[str, tuple[str, dict[str, Any], Callable[..., list[dict]]]] = {
    "futures-one-way": ("futures", {"positionMode": "ONE_WAY"}, one_way),
    "futures-hedge": ("futures", {"positionMode": "HEDGE"}, hedge),
    "spot": ("spot", {}, spot),
}


def _normalize(value: Any, names: dict[str, str]) -> Any:
    """Random ids become stable tokens in order of first appearance."""
    text = json.dumps(value, sort_keys=True, default=str)

    def token(match: re.Match[str]) -> str:
        found = match.group(0)
        if found not in names:
            names[found] = f"{found[:3]}#{sum(1 for key in names if key[:3] == found[:3]) + 1}"
        return names[found]

    return json.loads(ID.sub(token, text))


VOLATILE = {"lagMs", "timing", "updatedAtMs", "observedMs", "observed_ms"}


def _strip(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _strip(item) for key, item in value.items() if key not in VOLATILE}
    if isinstance(value, list):
        return [_strip(item) for item in value]
    return value


def run_variant(name: str, tmp_path: Path) -> dict[str, Any]:
    market_type, settings, script = VARIANTS[name]
    clock, market = Clock(T0 - 30_000), FakeMarket()
    store = TradingStore(tmp_path / f"{name}.sqlite3")
    service = TradingAccountService(store, snapshot_dir=tmp_path / f"{name}-snaps", market=market, clock=clock)
    try:
        account = service.create_account({"kind": "practice", "name": name, "settings": {**SETTINGS, **settings}})["id"]
        instrument = ("binance", market_type, "BTCUSDT")
        rejected: list[dict[str, Any]] = []
        last = None
        for index, candle in enumerate(candles()):
            start = candle["time"] * 1000
            if last is not None:
                for request in script(service, account, index, last):
                    clock.now = start - 1_000
                    try:
                        _order(service, account, market_type, **request)
                    except TradingAccountError as exc:
                        rejected.append({"bar": index, "code": exc.code})
            for step, offset in enumerate(FORMING):
                clock.now = start + offset
                service.apply_market_bars(instrument, [_forming(candle, step)], observed_ms=clock.now)
            clock.now = start + 59_999
            market.bar = {**candle}
            service.apply_market_bars(instrument, [candle], observed_ms=clock.now)
            last = candle
        names: dict[str, str] = {}
        views = _normalize(_strip({
            "fills": service.list_fills(account),
            "orders": service.list_orders(account),
            "trades": service.list_trades(account),
            "summary": service.account_summary(account),
        }), names)
    finally:
        store.close()
    fills = views["fills"]["fills"]
    orders = views["orders"]["orders"]
    return {
        "summary": {
            "fills": len(fills),
            "orders": len(orders),
            "order_states": sorted({f"{row['status']}:{row.get('cancelReason') or ''}".rstrip(":") for row in orders}),
            "rejected": rejected,
            "fill_rows": [f"{row['tsMs']} {row.get('positionSide') or ''} {row['side']} {row['qty']} @ {row['price']} "
                          f"fee {row['fee']} {row['liquidity']}".replace("  ", " ") for row in fills],
            "equity": views["summary"].get("equity"),
            "available": views["summary"].get("available"),
        },
        "digests": {key: "sha256:" + sha256_hex(value) for key, value in views.items()},
    }


def build(tmp_path: Path) -> dict[str, Any]:
    return {"schema": SCHEMA, "scenario": scenario(), "settings": SETTINGS, "forming_offsets_ms": list(FORMING),
            "variants": {name: run_variant(name, tmp_path) for name in VARIANTS}}


def golden_path() -> Path:
    return GOLDEN_DIR / "practice-accounts.json"


def assert_baseline(current: Mapping[str, Any]) -> None:
    target = golden_path()
    if os.environ.get(UPDATE_ENV) == "1":
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(current, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        return
    if not target.is_file():
        pytest.fail(f"missing practice baseline; generate it with {UPDATE_ENV}=1 and review the diff", pytrace=False)
    golden = json.loads(target.read_text(encoding="utf-8"))
    changed = sorted(f"{name}.{key}" for name in golden["variants"]
                     for key, value in golden["variants"][name]["digests"].items()
                     if (current["variants"].get(name) or {}).get("digests", {}).get(key) != value)
    assert canonical_json(golden) == canonical_json(dict(current)), (
        f"practice baseline changed ({', '.join(changed) or 'summary only'}). If ADR-BACKTEST-015 records this "
        f"change, regenerate with {UPDATE_ENV}=1 and commit the reviewed diff.")
