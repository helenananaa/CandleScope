from dataclasses import replace
from decimal import Decimal
import random

from app.replay.training.account import InstrumentRule, MaintenanceTier
from app.replay.training import storage
from app.replay.broker.interval_index import PriceRangeIndex


def rule():
    return InstrumentRule(
        track_id="track-1",
        rule_version="INTERVAL_TEST",
        source_kind="BAR",
        price_tick="0.1",
        quantity_step="0.001",
        min_quantity="0.001",
        max_quantity="10000",
        min_notional="1",
        max_notional="1000000",
        quote_step="0.01",
        contract_size="1",
        max_leverage="20",
        liquidation_fee_bps="25",
        maintenance_tiers=(
            MaintenanceTier("1000", "0.005", "0"),
            MaintenanceTier("1000000", "0.01", "5"),
        ),
        mark_fidelity="PINNED_MARK",
        rule_fidelity="VERSIONED_EXCHANGE_RULE",
        effective_virtual_time_ms=0,
    )


def test_direct_risk_search_matches_reference_across_money_rounding(monkeypatch):
    rng = random.Random(93541)
    direct = storage._direct_liquidation_tick
    hits = 0
    for i in range(3000):
        instrument = replace(
            rule(),
            price_tick=rng.choice(["0.0001", "0.1", "1"]),
            quote_step=rng.choice(["0.000001", "0.01", "1"]),
            contract_size=rng.choice(["0.1", "1", "100"]),
        )
        if i % 5 == 0:
            instrument = replace(
                instrument,
                maintenance_tiers=(
                    MaintenanceTier("1000", "0.005", "0"),
                    MaintenanceTier("1000000", "0.02", "3"),
                ),
            )  # Discontinuous rules must preserve the reference search.
        mark = Decimal(rng.randrange(1, 10000000)) / 100
        quantity = Decimal(rng.choice([1, 10, 1000, 10000])) / 1000
        kwargs = dict(
            mark_price=mark,
            scope_equity=Decimal(rng.randrange(-100, 10000000)) / 100,
            scope_maintenance_margin=instrument.maintenance_margin(
                quantity * Decimal(instrument.contract_size) * mark,
                extend_last_tier=True,
            )
            + Decimal(rng.randrange(0, 10000)) / 100,
            absolute_quantity=quantity,
            position_side=rng.choice(["LONG", "SHORT"]),
            rule=instrument,
        )

        def counted(**args):
            nonlocal hits
            result = direct(**args)
            hits += result is not None
            return result

        monkeypatch.setattr(storage, "_direct_liquidation_tick", counted)
        actual = storage._project_liquidation_price_pair(**kwargs)
        monkeypatch.setattr(storage, "_direct_liquidation_tick", lambda **args: None)
        expected = storage._project_liquidation_price_pair(**kwargs)
        assert actual == expected, kwargs
    assert hits > 500


def test_direct_search_reduces_exact_maintenance_evaluations(monkeypatch):
    instrument = rule()
    kwargs = dict(
        mark_price=Decimal("100000"),
        scope_equity=Decimal("10000"),
        scope_maintenance_margin=instrument.maintenance_margin(Decimal("100000")),
        absolute_quantity=Decimal("1"),
        position_side="LONG",
        rule=instrument,
    )
    calls = 0
    original = InstrumentRule.maintenance_margin

    def counted(self, *args, **options):
        nonlocal calls
        calls += 1
        return original(self, *args, **options)

    monkeypatch.setattr(InstrumentRule, "maintenance_margin", counted)
    actual = storage._project_liquidation_price_pair(**kwargs)
    optimized_calls = calls
    calls = 0
    monkeypatch.setattr(storage, "_direct_liquidation_tick", lambda **args: None)
    assert storage._project_liquidation_price_pair(**kwargs) == actual
    assert optimized_calls < calls // 2


def test_range_tree_matches_linear_envelope_and_extrema():
    rng = random.Random(771)
    ranges = tuple(
        (Decimal(n), Decimal(n + rng.randrange(20)))
        for n in (rng.randrange(1000) for _ in range(10081))
    )
    tree = PriceRangeIndex(ranges)
    for _ in range(500):
        start = rng.randrange(len(ranges))
        end = rng.randrange(start, len(ranges) + 1)
        lower, upper = sorted(
            (Decimal(rng.randrange(1100)), Decimal(rng.randrange(1100)))
        )
        expected = next(
            (
                i
                for i in range(start, end)
                if ranges[i][0] < lower or ranges[i][1] > upper
            ),
            end,
        )
        assert tree.first_outside(lower, upper, start=start, end=end) == expected
        assert tree.range_bounds(start=start, end=end) == (
            (min(p[0] for p in ranges[start:end]), max(p[1] for p in ranges[start:end]))
            if start < end
            else None
        )


def test_safe_week_is_excluded_from_root_summary():
    tree = PriceRangeIndex(((Decimal("90"), Decimal("110")),) * 10080)

    class Counting(list):
        reads = 0

        def __getitem__(self, key):
            self.reads += 1
            return super().__getitem__(key)

    tree.low, tree.high = Counting(tree.low), Counting(tree.high)
    assert (
        tree.first_outside(Decimal("80"), Decimal("120"), start=0, end=10080) == 10080
    )
    assert tree.low.reads == tree.high.reads == 1
