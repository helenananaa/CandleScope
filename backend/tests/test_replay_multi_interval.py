from decimal import Decimal, localcontext
import random

from app.replay.training.account import instrument_rule_from_broker_config
from app.replay.training.multi_interval import (
    IntervalLeg,
    ordered_equity_summary,
    safe_envelope,
)
from tests.fixtures.replay.broker_fakes import CONFIG
from app.replay.training.portfolio_prices import PortfolioPrices


def test_multi_transport_capacity_is_recorded_and_old_commands_default_to_64():
    from app.replay.commands import parse_command
    from app.replay.constants import REPLAY_PROTOCOL
    from app.replay.internal_commands import InternalCommandType
    from app.replay.models import ReplayCommand

    payload = dict(
        target_virtual_time_ms=60000,
        max_events=1,
        require_empty_account=False,
        snapshot_only=False,
    )

    def parsed(extra):
        return parse_command(
            ReplayCommand(
                protocol=REPLAY_PROTOCOL,
                command_id="transport",
                client_instance_id="client",
                expected_revision=0,
                type=InternalCommandType.MULTI_SHARED_INDEXED_INTERVAL,
                payload={**payload, **extra},
            )
        ).values

    assert parsed({})["transport_tail_bars"] == 64
    assert parsed({"transport_tail_bars": 16})["transport_tail_bars"] == 16


def leg(track, side="LONG", quantity="1", entry="100", isolated="1000"):
    rule = instrument_rule_from_broker_config(
        track_id=track,
        source_kind="BAR",
        broker_config=CONFIG.to_dict(),
        effective_virtual_time_ms=0,
    )
    return IntervalLeg(
        track, side, Decimal(quantity), Decimal(entry), rule, Decimal(isolated)
    )


def test_packed_prices_match_reference_across_windows_and_cohorts():
    rng = random.Random(3261)
    positions = [
        leg(str(i), side, quantity="0.015", entry="100.002")
        for i in range(8)
        for side in ("LONG", "SHORT")
        if i % 3 or side == "LONG"
    ]
    events = [
        (
            i // 5 + 1000,
            30,
            str(rng.randrange(8)),
            i,
            Decimal(rng.randrange(50001, 150000)) / 1000,
        )
        for i in range(6000)
    ]
    packed = PortfolioPrices.build(events)
    assert packed.packed is not None
    for start, end in ((999, 2200), (1100, 1900), (1400, 1400), (1900, 2199)):
        prices = {str(i): Decimal("100.0001") for i in range(8)}
        for e in events:
            if e[0] <= start:
                prices[e[2]] = e[4]
        kwargs = dict(
            cash=Decimal("10000.00001"), legs=positions, initial_prices=prices
        )
        expected = ordered_equity_summary(
            **kwargs,
            events=[(e[0] - 999, *e[1:]) for e in events if start < e[0] <= end],
        )
        actual = packed.summary(**kwargs, start=start, end=end, delta=999)
        for key in ("first", "last", "peak", "trough", "max_drawdown"):
            assert Decimal(actual[key]) == Decimal(expected[key]), key
        assert actual["trough_time_ms"] == expected["trough_time_ms"]
        assert actual["events"] == expected["events"]


def test_packed_prices_bound_scaling_and_preserve_exotic_precision_fallback():
    packed = PortfolioPrices.build([(1, 30, "a", 1, Decimal("1E-100000"))])
    assert packed.packed is None
    kwargs = dict(
        cash=Decimal(1000),
        legs=[leg("a", quantity="0.000000000000000000000000000001")],
        initial_prices={"a": Decimal(100)},
    )
    assert packed.summary(**kwargs, start=0, end=1) == ordered_equity_summary(
        **kwargs, events=packed.events
    )


def test_combination_extrema_follow_time_and_cohort_not_independent_extrema():
    legs = [leg("a"), leg("b")]
    summary = ordered_equity_summary(
        cash=Decimal(1000),
        legs=legs,
        initial_prices={"a": Decimal(100), "b": Decimal(100)},
        events=[
            (1, 30, "a", 1, Decimal(150)),
            (1, 30, "b", 1, Decimal(50)),
            (2, 30, "a", 2, Decimal(50)),
            (2, 30, "b", 2, Decimal(150)),
        ],
    )
    assert Decimal(summary["peak"]) == Decimal(summary["trough"]) == 1000
    assert Decimal(summary["max_drawdown"]) == 0


def test_eight_track_integer_summary_matches_decimal_with_unequal_grids():
    rng = random.Random(1843)
    legs = [
        leg(f"track-{i}", "SHORT" if i % 2 else "LONG", str(Decimal(i + 1) / 100))
        for i in range(8)
    ]
    prices = {f"track-{i}": Decimal(100) for i in range(8)}
    events = [
        (
            i,
            30,
            f"track-{rng.randrange(8)}",
            i,
            Decimal(rng.randrange(5000, 15000)) / 100,
        )
        for i in range(1000)
    ]
    expected = []
    with localcontext() as ctx:
        ctx.prec = 60
        for _time, _phase, track, _sequence, price in events:
            prices[track] = price
            expected.append(
                Decimal(10000)
                + sum(
                    (
                        position.weight * (prices[position.track_id] - position.entry)
                        for position in legs
                    ),
                    Decimal(0),
                )
            )
    actual = ordered_equity_summary(
        cash=Decimal(10000),
        legs=legs,
        initial_prices={track: Decimal(100) for track in prices},
        events=events,
    )
    peak = Decimal(10000)
    drawdown = Decimal(0)
    for value in expected:
        peak = max(peak, value)
        drawdown = max(drawdown, peak - value)
    assert actual["integer_path"] is True
    assert Decimal(actual["last"]) == expected[-1]
    assert Decimal(actual["peak"]) == max([Decimal(10000), *expected])
    assert Decimal(actual["trough"]) == min([Decimal(10000), *expected])
    assert Decimal(actual["max_drawdown"]) == drawdown


def test_unusual_precision_uses_reference_decimal_formula():
    position = leg("a", quantity="0.000000000000000000000000000001")
    result = ordered_equity_summary(
        cash=Decimal(10000),
        legs=[position],
        initial_prices={"a": Decimal(100)},
        events=[(1, 30, "a", 1, Decimal(101))],
    )
    assert result["integer_path"] is False
    with localcontext() as ctx:
        ctx.prec = 60
        assert Decimal(result["last"]) == Decimal(10000) + Decimal("1e-30")


def test_cross_and_isolated_safety_are_not_net_position_safety():
    legs = [leg("a", isolated="0.01"), leg("a", "SHORT", isolated="0.01")]
    bounds = {"a": (Decimal(50), Decimal(150))}
    assert safe_envelope(
        cash=Decimal(1000), legs=legs, bounds=bounds, margin_mode="CROSS"
    )
    assert not safe_envelope(
        cash=Decimal(100000), legs=legs, bounds=bounds, margin_mode="ISOLATED"
    )
    assert not safe_envelope(
        cash=Decimal(10), legs=legs, bounds=bounds, margin_mode="CROSS"
    )
    assert not safe_envelope(
        cash=Decimal(1000),
        legs=legs,
        bounds=bounds,
        margin_mode="CROSS",
        reserved_margin=Decimal(999),
    )


def test_tier_crossing_requires_exact_boundary():
    position = leg("a", quantity="400")
    assert not safe_envelope(
        cash=Decimal(100000),
        legs=[position],
        bounds={"a": (Decimal(100), Decimal(200))},
        margin_mode="CROSS",
    )


def test_compact_short_interval_retains_valid_warmup_checkpoint():
    from app.replay.bars.builder import ReplayBarBuilder
    from app.replay.broker.shared_prepared import SharedPreparedInterval
    from tests.fixtures.replay.broker_fakes import bar

    warmup = tuple(bar(i, 100) for i in range(-200, 0))
    start = bar(0, 100).open_time_ms
    original = ReplayBarBuilder(
        base_interval="1m",
        display_interval="1m",
        replay_start_ms=start,
        warmup_bars=warmup,
        max_closed_bars=2048,
    )
    interval = object.__new__(SharedPreparedInterval)
    interval.origin = original
    interval.bars = (bar(0, 100),)
    compact = interval.builder_at(1, tail_limit=64)
    restored = ReplayBarBuilder(
        base_interval="1m",
        display_interval="1m",
        replay_start_ms=start,
        warmup_bars=warmup,
        max_closed_bars=64,
    )
    restored.restore(compact.snapshot())
    assert restored.snapshot() == compact.snapshot()
    assert len(compact.closed_bars) == 64
    assert len(original.closed_bars) == 200
