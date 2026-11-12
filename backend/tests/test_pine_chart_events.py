"""Actual external-account Pine; synthetic rows never become fill prices."""

from copy import deepcopy
import pytest
from tests.test_chart_pine_callbacks import service, payload, RecordingProvider, pytestmark
from tests.test_backtest_dual_clock import _trade

SOURCE = """//@version=6
strategy("Chart events",calc_on_every_tick=true,calc_on_order_fills=true)
var int ordinary=0
varip int persistent=0
varip bool entered=false
varip bool exited=false
ordinary+=1
persistent+=1
if not entered
    strategy.entry("L",strategy.long,qty=1)
    entered:=true
if strategy.position_size>0 and not exited
    strategy.close("L")
    exited:=true
plot(close)
plot(ordinary)
plot(persistent)
plot(strategy.position_size)
"""


def tape():
    return tuple(
        _trade(i + 1, stamp, str(price), "100")
        for i, (stamp, price) in enumerate(
            [
                (1000, 10),
                (2000, 11),
                (60000, 16),
                (70000, 17),
                (119999, 15),
                (120000, 8),
                (130000, 9),
                (179999, 14),
            ]
        )
    )


@pytest.mark.parametrize(
    "transform", ["heikin-ashi", "renko", "point-and-figure", "kagi", "line-break"]
)
def test_actual_prints_and_fill_callbacks_share_chart_ordinals_and_real_matching(
    service, transform
):
    body = payload(
        service,
        SOURCE,
        signal_chart={"transform": transform, "box_size": 2, "min_tick": 1, "reversal_amount": 2},
        end_time_ms=180000,
    )
    run = service.create_run(body, idempotency_key="events", now_ms=3)
    provider = RecordingProvider()
    completed = service.execute_dual_clock_run(
        run["run_id"],
        events=tape(),
        provider=provider,
        now_ms=4,
        observation_market={"venue": "binance", "symbol": "BTCUSDT"},
    )
    assert completed["state"] == "COMPLETED", completed
    fills = completed["report"]["fills"]
    assert [float(row["price"]) for row in fills] == [11, 16]
    frames = provider.observations
    assert [f.sequence for f in frames] == list(range(1, len(frames) + 1))
    assert any(f.features["pineExecutionContext"]["trigger"] == "order_fill" for f in frames)
    assert any(f.features["pineExecutionContext"]["trigger"] == "realtime_tick" for f in frames)
    assert all(f.bar["open_time_ms"] <= f.event_time_ms for f in frames)
    assert all(f.event_time_ms == f.watermark_ms for f in frames)
    assert [f.features["pineExecutionPass"]["barIndex"] for f in frames] == sorted(
        f.features["pineExecutionPass"]["barIndex"] for f in frames
    )


@pytest.mark.parametrize(
    "transform", ["heikin-ashi", "renko", "point-and-figure", "kagi", "line-break"]
)
def test_event_clock_resumes_forming_bars_without_replaying_market_fills(service, transform):
    import json

    body = payload(
        service,
        SOURCE,
        signal_chart={"transform": transform, "box_size": 2, "min_tick": 1, "reversal_amount": 2},
        end_time_ms=180000,
    )

    def execute(run):
        return service.execute_dual_clock_run(
            run["run_id"],
            events=tape(),
            provider=RecordingProvider(),
            now_ms=4,
            observation_market={"venue": "binance", "symbol": "BTCUSDT"},
        )

    baseline = execute(service.create_run(body, idempotency_key="reference", now_ms=3))
    run = service.create_run(body, idempotency_key="resume", now_ms=3)
    original = service.repository.save_checkpoint

    def save_then_interrupt(value):
        saved = original(value)
        if value["sequence"] == 2:
            raise KeyboardInterrupt("durable event checkpoint")
        return saved

    service.repository.save_checkpoint = save_then_interrupt
    try:
        with pytest.raises(KeyboardInterrupt):
            execute(run)
    finally:
        service.repository.save_checkpoint = original
    checkpoint = json.loads(service.repository.latest_checkpoint(run["run_id"])["payload_json"])
    assert checkpoint["planner"]["signal_input"]["series"]["active"] is not None
    assert service.requeue_interrupted_run(run["run_id"], expected_generation=1, now_ms=8)
    resumed = execute(run)
    for key in ("decision_hash", "fill_hash", "ledger_hash", "report_hash"):
        assert resumed["result"][key] == baseline["result"][key], key


@pytest.mark.parametrize("transform", ["heikin-ashi", "renko"])
def test_bar_fill_callbacks_and_independent_cost_accounts_keep_the_chart_clock(service, transform):
    from tests.test_pine_cost_sensitivity import config, execute, scenarios
    from tests.test_chart_strategy_signals import event

    script = SOURCE.replace("calc_on_every_tick=true,", "")
    from app.simulation.execution_realism import PINE_BAR_PATH_SCENARIO

    body = config(
        service,
        source=script,
        signal_chart={"transform": transform, "box_size": 2, "min_tick": 1},
        bar_path_scenario=PINE_BAR_PATH_SCENARIO,
    )
    completed = execute(
        service,
        body,
        events=tuple(
            event(i, c, opening=c - 1, high=c + 1, low=c - 2)
            for i, c in enumerate([10, 16, 17, 11, 8])
        ),
    )
    assert scenarios(completed)["BASELINE"]["hashes"]["fill"] == completed["result"]["fill_hash"]


@pytest.mark.parametrize("ticks,fills", [(False, True), (True, False)])
def test_each_event_setting_alone_uses_the_same_shared_clock(service, ticks, fills):
    script = SOURCE.replace(
        "calc_on_every_tick=true", f"calc_on_every_tick={str(ticks).lower()}"
    ).replace("calc_on_order_fills=true", f"calc_on_order_fills={str(fills).lower()}")
    body = payload(
        service,
        script,
        signal_chart={"transform": "renko", "box_size": 2, "min_tick": 1},
        end_time_ms=180000,
    )
    run = service.create_run(body, idempotency_key="one-setting", now_ms=3)
    provider = RecordingProvider()
    completed = service.execute_dual_clock_run(
        run["run_id"],
        events=tape(),
        provider=provider,
        now_ms=4,
        observation_market={"venue": "binance", "symbol": "BTCUSDT"},
    )
    assert completed["state"] == "COMPLETED"
    contexts = [f.features["pineExecutionContext"]["trigger"] for f in provider.observations]
    assert ("realtime_tick" in contexts) == ticks
    assert ("order_fill" in contexts) == fills


def test_real_millisecond_ticks_resolve_the_known_market_grid_before_building_lines(service):
    body = payload(
        service,
        SOURCE,
        signal_chart={"transform": "line-break"},
        price_tick=".01",
        end_time_ms=60000,
    )
    run = service.create_run(body, idempotency_key="millisecond-grid", now_ms=3)
    provider = RecordingProvider()
    data = tuple(
        _trade(i + 1, 1001 + i, str(price), "100") for i, price in enumerate([100, 100.1, 100.2])
    )
    completed = service.execute_dual_clock_run(
        run["run_id"],
        events=data,
        provider=provider,
        now_ms=4,
        observation_market={"venue": "binance", "symbol": "BTCUSDT"},
    )
    assert completed["state"] == "COMPLETED"
    assert any(
        float(f.bar["close"]) == 100.1 and f.features["pineExecutionPass"]["confirmed"]
        for f in provider.observations
    )
    assert {f.event_time_ms for f in provider.observations} == {1001, 1002, 1003}
    assert provider.observations[0].bar["open_time_ms"] == 1001


def test_real_liquidation_feedback_cannot_advance_the_physical_chart_clock(service):
    import json
    from tests.test_chart_pine_liquidation import text, tape, execute
    from tests.test_chart_pine_risk_stops import config

    body = config(
        service,
        text(),
        tape=True,
        signal_chart={"transform": "heikin-ashi"},
        account_model="LINEAR_PERP_ONE_WAY_V2",
        leverage="10",
        funding_mode="OFF",
        contract_data_mode="HISTORICAL_CONTRACT_V1",
    )
    run = service.create_run(body, idempotency_key="chart-liquidation", now_ms=3)
    checkpoints = []
    save = service.repository.save_checkpoint

    def capture(value):
        result = save(value)
        if value["sequence"] == 5:
            checkpoints.append(json.loads(value["payload_json"]))
        return result

    service.repository.save_checkpoint = capture
    try:
        provider = RecordingProvider()
        result = execute(service, run, tape(), provider)
    finally:
        service.repository.save_checkpoint = save
    assert result["state"] == "COMPLETED", result
    assert result["report"]["fills"][-1]["reason"] == "ACCOUNT_LIQUIDATION"
    frame = next(f for f in provider.observations if f.event_time_ms == 70000)
    assert float(frame.account_view["position_size"]) == 0
    assert float(frame.bar["close"]) == 100
    assert checkpoints[0]["planner"]["signal_input"]["series"]["last_key"] == 4


@pytest.mark.parametrize("order,price,stamp", [("limit=14", 14, 120000), ("stop=14", 17, 70000)])
def test_tick_chart_orders_wait_for_real_post_signal_limit_and_stop_prices(
    service, order, price, stamp
):
    script = """//@version=6
strategy("Real eligibility",calc_on_every_tick=true,calc_on_order_fills=true)
varip bool sent=false
if barstate.isconfirmed and close>=14 and not sent
    sent:=true
    strategy.entry("L",strategy.long,qty=1,ORDER)
""".replace(
        "ORDER", order
    )
    body = payload(
        service,
        script,
        signal_chart={"transform": "renko", "box_size": 2, "min_tick": 1},
        end_time_ms=180000,
    )
    run = service.create_run(body, idempotency_key="real-crossing", now_ms=3)
    completed = service.execute_dual_clock_run(
        run["run_id"],
        events=tape(),
        provider=RecordingProvider(),
        now_ms=4,
        observation_market={"venue": "binance", "symbol": "BTCUSDT"},
    )
    assert completed["state"] == "COMPLETED", completed
    # The existing tape matcher fills crossed limits at the order level.
    # Eligibility and crossing still come exclusively from later real prints.
    assert [
        (float(row["price"]), row["event_time_ms"]) for row in completed["report"]["fills"]
    ] == [(price, stamp)]
