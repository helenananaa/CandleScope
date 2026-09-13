"""Frozen benchmark strategy sources; no test/API imports at worker startup."""

SMA = """strategy("SMA Cross")
fast = sma(close, 3)
slow = sma(close, 5)

if crossover(fast, slow)
  target_position(1)
else if crossunder(fast, slow)
  target_position(0)
"""

RSI = """strategy("RSI Reversal")
value = rsi(close, 14)

if value < 30
  target_position(1)
else if value > 70
  target_position(0)
"""
