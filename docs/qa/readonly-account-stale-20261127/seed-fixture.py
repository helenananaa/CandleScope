"""Seed a synthetic read-only account (no credentials, no exchange calls).
Usage: python seed.py <data_dir> <paused|error> <snapshot_age_minutes>"""
import sys, time, json
from pathlib import Path
from app.readonly_accounts.repository import AccountRepository
from app.readonly_accounts import normalization as normal

data, scenario, age = Path(sys.argv[1]), sys.argv[2], float(sys.argv[3])
root = data / "readonly-accounts"
repo = AccountRepository(root)
now = int(time.time() * 1000)
at = now - int(age * 60_000)
instruments = {
    "BTC-USDT-SWAP": {"instType": "SWAP", "instId": "BTC-USDT-SWAP", "ctType": "linear", "settleCcy": "USDT", "ctValCcy": "BTC", "ctVal": "0.01", "lotSz": "0.01"},
    "ETH-USD-SWAP": {"instType": "SWAP", "instId": "ETH-USD-SWAP", "ctType": "inverse", "settleCcy": "ETH", "ctValCcy": "USD", "ctVal": "10", "lotSz": "1"},
}
contracts = {key: normal.Contract.from_okx(raw) for key, raw in instruments.items()}
repo.bind("10000000001", "0" * 31 + "1" if scenario == "error" else "1" * 32, at - 86_400_000)
if scenario == "paused":
    repo.forget_credential()
else:
    repo.status("synced", success=True)
positions = [
    {"instType": "SWAP", "instId": "BTC-USDT-SWAP", "posSide": "long", "pos": "12", "mgnMode": "cross", "avgPx": "91234.5", "markPx": "92010.1",
     "upl": "93.072", "posId": "1234567890", "uTime": str(at - 5000), "cTime": str(at - 3_600_000), "lever": "10", "liqPx": "83512.7",
     "margin": "", "imr": "110.412", "mmr": "4.416", "mgnRatio": "85.31", "ccy": "USDT", "availPos": "12"},
    {"instType": "SWAP", "instId": "ETH-USD-SWAP", "posSide": "short", "pos": "30", "mgnMode": "isolated", "avgPx": "3120.4", "markPx": "3098.2",
     "upl": "0.0006889", "posId": "1234567891", "uTime": str(at - 9000), "cTime": str(at - 7_200_000), "lever": "5", "liqPx": "3702.95",
     "margin": "0.01937", "imr": "", "mmr": "0.000484", "mgnRatio": "38.2", "ccy": "ETH", "availPos": "30"},
]
repo.save_snapshot("positions", {"raw": positions, "positions": [normal.position(raw, contracts[raw["instId"]]) for raw in positions]}, at)
order = {"instType": "SWAP", "instId": "BTC-USDT-SWAP", "posSide": "long", "side": "buy", "ordId": "555000111", "state": "live",
         "sz": "4", "accFillSz": "0", "px": "89000", "uTime": str(at - 60_000), "cTime": str(at - 60_000), "lever": "10", "tdMode": "cross"}
repo.save_snapshot("open_orders", [{"raw": order, "order": normal.order(order, contracts["BTC-USDT-SWAP"])}], at)
balances = [{"adjEq": "", "totalEq": "10342.7", "isoEq": "60.02", "imr": "110.412", "mmr": "4.416", "mgnRatio": "", "notionalUsd": "11105.2",
             "uTime": str(at - 2000), "details": [
                 {"ccy": "USDT", "eq": "10234.51", "cashBal": "10141.438", "availEq": "10124.098", "availBal": "10031.026", "frozenBal": "110.412",
                  "isoEq": "0", "upl": "93.072", "uTime": str(at - 2000), "eqUsd": "10234.51"},
                 {"ccy": "ETH", "eq": "0.0351", "cashBal": "0.0351", "availEq": "", "availBal": "0.0157", "frozenBal": "0.01937",
                  "isoEq": "0.0200589", "upl": "0.0006889", "uTime": str(at - 2000), "eqUsd": "108.75"}]}]
repo.save_snapshot("balances", balances, at)
print(json.dumps({"root": str(root), "scenario": scenario, "snapshotMs": at}))
