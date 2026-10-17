"""Completed net-position episodes derived from host fills, never rematched.

An episode starts when a flat account opens and ends at flat or reversal.
Partial closes and pyramiding belong to the same episode. Fees on a reversal
are allocated by closed/opened quantity, as is the average-cost host account.
"""
from decimal import Decimal


def closed_trades(fills):
    zero = Decimal(0)
    position, basis = zero, zero
    episode = None
    completed = []
    for fill in fills:
        qty, price, fee = (Decimal(str(fill[key])) for key in ("qty", "price", "fee"))
        direction = Decimal(1) if fill["side"] == "BUY" else Decimal(-1)
        closing = min(abs(position), qty) if position * direction < 0 else zero
        opening = qty - closing
        close_fee = fee * closing / qty
        if closing:
            episode["profit"] += (price - basis) * closing * (1 if position > 0 else -1) - close_fee
            episode["exit_value"] += price * closing
            episode["closed_qty"] += closing
            position += direction * closing
            if position == 0:
                completed.append({
                    "id": str(len(completed) + 1), "side": episode["side"],
                    "entryTime": episode["entry_time_ms"] / 1000,
                    "exitTime": fill["event_time_ms"] / 1000,
                    "entryPrice": str(episode["entry_value"] / episode["opened_qty"]),
                    "exitPrice": str(episode["exit_value"] / episode["closed_qty"]),
                    "qty": str(episode["closed_qty"]), "profit": str(episode["profit"]),
                    "return_percent": str(episode["profit"] / episode["entry_value"] * 100),
                    "basis": "host-net-position-episode/1",
                })
                episode, basis = None, zero
        if opening:
            if episode is None:
                episode = {"side": "long" if direction > 0 else "short",
                           "entry_time_ms": fill["event_time_ms"], "profit": zero,
                           "entry_value": zero, "exit_value": zero,
                           "opened_qty": zero, "closed_qty": zero}
            basis = (basis * abs(position) + price * opening) / (abs(position) + opening)
            episode["profit"] -= fee - close_fee
            episode["entry_value"] += price * opening
            episode["opened_qty"] += opening
            position += direction * opening
    return completed
