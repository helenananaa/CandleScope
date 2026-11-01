import json
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

root = Path(__file__).parent
receipt = json.loads((root / 'acceptance-basic.json').read_text())
assert receipt['passed']
steps = {s['name']: s['evidence'] for s in receipt['steps']}
initial = steps['created-paused']['tracks']
buy = steps['buy-filled']['tracks']['portfolio']
closed = steps['closed-cycle']['tracks']['portfolio']
start = 1700000040000
index = (initial['tracks'][0]['cursor']['virtual_time_ms'] - start) // 60000
def base(i):
    return Decimal(30000 + (i % 80) * 2) + Decimal(i // 80) / 4
entry = base(index) * Decimal('1.0001')
exit_index = index + 4
exit_mark = base(exit_index) + (4 if exit_index % 2 == 0 else -3)
exit_price = exit_mark * Decimal('0.9999')
qty = Decimal('0.01')
fee = lambda price: (price * qty * Decimal('0.0005')).quantize(Decimal('.00000001'), rounding=ROUND_HALF_UP)
fees = fee(entry) + fee(exit_price)
pnl = (exit_price - entry) * qty
cash = Decimal(10000) + pnl - fees
assert Decimal(initial['tracks'][0]['public_price']) == base(index)
assert Decimal(buy['positions'][0]['position']['entry_price']) == entry
assert Decimal(buy['positions'][0]['position']['quantity']) == qty
assert Decimal(buy['fees_paid']) == fee(entry)
assert closed['positions'] == []
assert closed['history']['fills_total'] == 2
assert closed['history']['orders_total'] == 2
assert Decimal(closed['realized_pnl']) == pnl
assert Decimal(closed['fees_paid']) == fees
assert Decimal(closed['cash_balance']) == cash
assert Decimal(closed['ledger']['reconciliation_delta']) == 0
result = dict(passed=True, source='independent Decimal arithmetic from the finite OHLCV formula, configured 1 bps market slippage and 5 bps taker fees', initial_index=index, exit_mark_index=exit_index, quantity=str(qty), entry=str(entry), exit=str(exit_price), fees=str(fees), realized_pnl=str(pnl), cash_balance=str(cash), scope='two deterministic one-way approximate-model market fills; no historical-exact account claim')
(root / 'financial-oracle.json').write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps(result))
