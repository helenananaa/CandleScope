"""seed-funding.py <data_dir> <ok|error>: funding snapshots on top of seed-account.py (no exchange calls)."""
import sys, time
from pathlib import Path
from app.readonly_accounts.repository import AccountRepository
from app.readonly_accounts import normalization as normal
from app.readonly_accounts.sync import three_months_before

data, scenario = Path(sys.argv[1]), sys.argv[2]
repo = AccountRepository(data / "readonly-accounts")
now = int(time.time() * 1000)
at = now - 90_000
H = 3_600_000
balances = [{"ccy": "USDT", "bal": "2500.75", "availBal": "2400.75", "frozenBal": "100"},
            {"ccy": "BTC", "bal": "0.0421", "availBal": "0.0421", "frozenBal": "0"},
            {"ccy": "ETH", "bal": "1.2", "availBal": "0", "frozenBal": "1.2"}]
repo.save_snapshot("funding_balances", {"balances": [normal.funding_balance(row) for row in balances]}, at - (25 * 60_000 if scenario == "error" else 0))
repo.save_snapshot("funding_balances_state", {"error": "ACCOUNT_NETWORK_UNAVAILABLE" if scenario == "error" else None}, at)
deposits = [{"depId": "88001", "ccy": "USDT", "chain": "USDT-TRC20", "amt": "1000", "state": "2", "ts": str(at - 2 * H), "to": "addr", "txId": "tx"},
            {"depId": "88002", "ccy": "BTC", "chain": "BTC-Bitcoin", "amt": "0.0121", "state": "0", "ts": str(at - 20 * 60_000)},
            {"depId": "88003", "ccy": "ETH", "chain": "ETH-ERC20", "amt": "1.2", "state": "12", "ts": str(at - 30 * H)}]
withdrawals = [{"wdId": "99001", "ccy": "USDT", "chain": "USDT-TRC20", "amt": "300", "fee": "1", "feeCcy": "USDT", "state": "2", "ts": str(at - 5 * H)},
               {"wdId": "99002", "ccy": "BTC", "chain": "BTC-Bitcoin", "amt": "0.005", "fee": "0.0001", "feeCcy": "BTC", "state": "-2", "ts": str(at - 50 * H)}]
transfers = [{"billId": "77001", "type": "1", "ccy": "USDT", "balChg": "500", "from": "6", "to": "18", "ts": str(at - 3 * H)},
             {"billId": "77002", "type": "1", "ccy": "USDT", "balChg": "-120.5", "from": "18", "to": "6", "ts": str(at - 26 * H)}]
history = {"deposits": [normal.deposit(r) for r in deposits], "withdrawals": [normal.withdrawal(r) for r in withdrawals],
           "transfers": [normal.transfer(r) for r in transfers], "fromMs": three_months_before(now), "throughMs": at,
           "complete": scenario != "error"}
repo.save_snapshot("funding_history", history, at)
repo.save_snapshot("funding_history_state", {"error": None, "complete": scenario != "error"}, at)
print("seeded", scenario)
