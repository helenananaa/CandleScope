"""Lazy signal batches: admit each plan before evaluating the next chart row.

The market loop owns admission and matching. Iterating a batch never advances
market prices. An empty batch therefore still permits real orders to fill.
"""
class ChartDecisionBatch:
    def __init__(self, plans):
        self.plans = plans


def decision_plans(value):
    return value.plans if isinstance(value, ChartDecisionBatch) else (value,)
