"""Seed only the isolated native QA profile with a labelled synthetic closed trade."""
import argparse
import json
from decimal import Decimal
from pathlib import Path

from app.trading_accounts.service import TradingAccountService
from app.trading_accounts.store import TradingStore

parser = argparse.ArgumentParser()
parser.add_argument("output", type=Path)
root = parser.parse_args().output.resolve()
assert root.name == "frontend-stability-native-20261102" and root.parent.name == "output"
data = root / "profile/data"
store = TradingStore(data / "trading-accounts.sqlite3")
try:
    service = TradingAccountService(store, snapshot_dir=data / "trading-snapshots")
    assert not service.list_accounts()["accounts"], "Keep prior fixtures; do not seed twice"
    account = service.create_account({"kind": "practice", "name": "QA synthetic practice snapshot",
                                      "settings": {"initialBalance": "1000"}})
    quantity = "0.1234567890123456789"
    with store.transaction() as db:
        for fid, side, price, fee, timestamp in [
            ("qa-native-open", "buy", "100", "0.0001", 1704067200000),
            ("qa-native-close", "sell", "120", "0.0002", 1704067260000),
        ]:
            store.insert(db, "fills", dict(id=fid, account_id=account["id"], exchange="binance",
                market_type="futures", symbol="BTCUSDT", side=side, qty=quantity, price=price,
                fee=fee, fee_currency="USDT", liquidity="taker", ts_ms=timestamp,
                source="explicit_native_qa_fixture", created_at_ms=timestamp))
    pnl = Decimal(quantity) * Decimal(20) - Decimal("0.0003")
    receipt = {"accountId": account["id"], "tradeId": "qa-native-open", "netPnl": format(pnl.normalize(), "f"),
               "balance": format((Decimal(1000) + pnl).normalize(), "f"), "quantity": quantity,
               "statsNetPnl": format(pnl.quantize(Decimal("0.00000001")), "f"),
               "scope": "Synthetic persisted practice trade, not a native matching or live execution test."}
    (root / "practice-fixture.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt))
finally:
    store.close()
