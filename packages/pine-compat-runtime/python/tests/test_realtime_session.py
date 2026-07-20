from __future__ import annotations

import pytest

import pine_compat


def _bar(time: int, close: float) -> dict[str, float | int]:
    return {
        "time": time,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 1.0,
    }


def _plot_values(result: dict, index: int) -> list[float | None]:
    return result["plots"][index]["values"]


def test_realtime_session_seeds_history_with_the_complete_dataset_endpoint() -> None:
    session = pine_compat.create_realtime_session(
        '''//@version=6
indicator("Dataset endpoint")
plot(last_bar_index)
plot(barstate.islast ? 1 : 0)
'''
    )

    result = session.seed([_bar(60_000, 1.0), _bar(120_000, 2.0)])

    assert pine_compat.REALTIME_SESSION_SCHEMA_VERSION == 1
    assert session.schema_version == 1
    assert session.is_seeded is True
    assert session.confirmed_bars == 2
    assert session.last_confirmed_time == 120_000
    assert session.forming_time is None
    assert _plot_values(result, 0) == [1.0, 1.0]
    assert _plot_values(result, 1) == [0.0, 1.0]


def test_realtime_session_rolls_back_var_and_carries_varip_between_forming_updates() -> None:
    session = pine_compat.compile_script(
        '''//@version=6
indicator("Rollback")
var float regular = 0.0
varip float intrabar = 0.0
regular += 1.0
intrabar += 1.0
plot(regular)
plot(intrabar)
'''
    ).realtime_session()
    session.seed([_bar(60_000, 1.0)])

    first = session.update_forming(_bar(120_000, 2.0))
    second = session.update_forming(_bar(120_000, 3.0))

    assert _plot_values(first, 0) == [1.0, 2.0]
    assert _plot_values(first, 1) == [1.0, 2.0]
    assert _plot_values(second, 0) == [1.0, 2.0]
    assert _plot_values(second, 1) == [1.0, 3.0]
    assert _plot_values(session.confirmed_result(), 0) == [1.0]
    assert _plot_values(session.confirmed_result(), 1) == [1.0]
    assert session.forming_time == 120_000

    confirmed = session.update_confirmed(_bar(120_000, 4.0))

    assert _plot_values(confirmed, 0) == [1.0, 2.0]
    assert _plot_values(confirmed, 1) == [1.0, 4.0]
    assert session.confirmed_bars == 2
    assert session.last_confirmed_time == 120_000
    assert session.forming_time is None
    assert session.result() == session.confirmed_result()


def test_realtime_session_applies_inputs_and_chart_context_once() -> None:
    source = '''//@version=6
indicator("Context")
factor = input.int(2, "Factor")
matches = syminfo.tickerid == "BINANCE:BTCUSDT.P" and timeframe.period == "60"
plot(close * factor + (matches ? 1 : 0))
'''
    analysis = pine_compat.analyze_script(source)
    factor_id = analysis["inputs"][0]["callSiteId"]
    session = pine_compat.create_realtime_session(
        source,
        input_overrides={factor_id: 3},
        chart_symbol="BINANCE:BTCUSDT.P",
        chart_timeframe="60",
    )

    seeded = session.seed([_bar(60_000, 2.0)])
    forming = session.update_forming(_bar(120_000, 4.0))

    assert _plot_values(seeded, 0) == [7.0]
    assert _plot_values(forming, 0) == [7.0, 13.0]


def test_realtime_session_rejects_ambiguous_or_regressive_lifecycle_updates() -> None:
    session = pine_compat.create_realtime_session(
        '//@version=6\nindicator("Lifecycle")\nplot(close)'
    )

    with pytest.raises(ValueError, match="must be seeded"):
        session.update_forming(_bar(60_000, 1.0))

    session.seed([_bar(60_000, 1.0)])
    with pytest.raises(ValueError, match="already been seeded"):
        session.seed([])

    session.update_forming(_bar(120_000, 2.0))
    with pytest.raises(ValueError, match="does not match forming time"):
        session.update_forming(_bar(180_000, 3.0))
    with pytest.raises(ValueError, match="does not match forming time"):
        session.update_confirmed(_bar(180_000, 3.0))

    session.update_confirmed(_bar(120_000, 2.0))
    with pytest.raises(ValueError, match="must be later than confirmed time"):
        session.update_confirmed(_bar(120_000, 2.0))
