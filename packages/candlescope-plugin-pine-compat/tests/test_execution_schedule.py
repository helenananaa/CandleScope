"""The explicit schedule reaches the installed core through both bridge routes."""
from copy import deepcopy

import pine_compat
import pytest

from candlescope_plugin_pine_compat import chart_strategy, external_strategy
from candlescope_plugin_pine_compat.execution_schedule import CONTRACT, PREFIX_CONTRACT
from candlescope_plugin_pine_compat.prefix_transport import PrefixInput
from test_external_incremental import wire, data

pytestmark = pytest.mark.skipif(getattr(pine_compat, "EXTERNAL_SCHEDULE_SCHEMA_VERSION", 0) != 1,
                                reason="requires explicit core schedule")


def request(count=2, *, realtime=False, endpoint=False):
    value = wire("""var int ordinary=0
varip int calls=0
ordinary+=1
calls+=1
plot(ordinary)
plot(calls)
plot(barstate.isconfirmed?1:0)
plot(barstate.ishistory?1:0)
plot(timenow)
if strategy.position_size>0
    strategy.close("L")
else
    strategy.entry("L",strategy.long,qty=2)
""")
    value["source"] = value["source"].replace('strategy("external")', 'strategy("external",calc_on_order_fills=true)')
    if endpoint:
        value["source"] += "plot(last_bar_index)\n"
    value.update(bars=[], accounts=[], execution_schedule=[], execution_schedule_contract=CONTRACT)
    for i in range(count):
        bar, account = data(i)
        value["bars"].append(bar)
        value["accounts"].append(account)
        group = []
        for index, position in enumerate([2, 0]):
            group.append(dict(evaluation=dict(bar=deepcopy(bar), account={**account, "position_size": position,
                "position_avg_price": 10 if position else None}, confirmed=index == 1,
                event_time_ms=bar["time"]*1000 + (59999 if index else 1000)),
                context=dict(bar_state="realtime" if realtime else "historical",
                             trigger="bar_close" if index else "order_fill", is_new=not realtime or index == 0)))
        value["execution_schedule"].append(group)
    return value


@pytest.mark.parametrize("module", [chart_strategy, external_strategy])
@pytest.mark.parametrize("realtime", [False, True])
def test_bridge_schedule_preserves_script_state_account_authority_and_both_time_units(module, realtime):
    identity = module.describe()
    assert identity["execution_schedule_contract"] == CONTRACT and identity["prefix_schedule"] == PREFIX_CONTRACT
    value = request(realtime=realtime)
    result = module.execute(value)
    assert [plot["values"] for plot in result["raw_output"]["plots"]] == [
        [1, 2], [2, 4], [1, 1], [0, 0] if realtime else [1, 1],
        [bar["time"]*1000+59999 for bar in value["bars"]]]
    assert [(item["bar_index"], item["pass_index"], item["action"]) for item in result["intents"]] == [
        (0, 0, "close"), (0, 1, "entry"), (1, 0, "close"), (1, 1, "entry")]
    assert result["account_authority"] == "candlescope" and "strategy" not in result["raw_output"]


@pytest.mark.parametrize("endpoint", [False, True])
def test_schedule_suffix_matches_full_run_for_incremental_and_endpoint_reconstruction(endpoint):
    value = request(3, endpoint=endpoint)
    initial = {**value, **{key: value[key][:1] for key in ("bars", "accounts", "execution_schedule")}}
    external_strategy.execute(initial)
    session = external_strategy._session
    for i in [1, 2]:
        actual = external_strategy.execute(dict(operation="append_prefix", prefix_base=i,
            **{key: value[key][i:i+1] for key in ("bars", "accounts", "execution_schedule")}))
        assert (external_strategy._session is None) == endpoint
        if not endpoint:
            assert external_strategy._session is session
    expected = external_strategy.execute(value)
    assert actual == expected


@pytest.mark.parametrize("change", ["missing_contract", "unknown_contract", "missing_schedule", "legacy_too", "numeric_time", "numeric_confirmation", "unknown_context"])
def test_explicit_mode_cannot_be_silently_dropped_or_coerced(change):
    value = request(1)
    if change == "missing_contract":
        value.pop("execution_schedule_contract")
    elif change == "unknown_contract":
        value["execution_schedule_contract"] += "0"
    elif change == "missing_schedule":
        value.pop("execution_schedule")
    elif change == "legacy_too":
        value["execution_passes"] = []
    elif change == "numeric_time":
        value["execution_schedule"][0][0]["evaluation"]["bar"]["time"] = 1.5
    elif change == "numeric_confirmation":
        value["execution_schedule"][0][0]["evaluation"]["confirmed"] = 1
    else:
        value["execution_schedule"][0][0]["context"]["ignored"] = True
    with pytest.raises(ValueError):
        external_strategy.execute(value)


def test_runtime_without_schedule_schema_never_advertises_or_accepts_it(monkeypatch):
    monkeypatch.setattr(pine_compat, "EXTERNAL_SCHEDULE_SCHEMA_VERSION", 0)
    assert "execution_schedule_contract" not in chart_strategy.describe()
    assert "execution_schedule_contract" not in external_strategy.describe()
    with pytest.raises(ValueError, match="EXTERNAL_SCHEDULE_INVALID"):
        external_strategy.execute(request(1))


def test_receiver_owns_input_and_rejects_schedule_mode_changes_before_extending_prefix():
    prefix = PrefixInput()
    value = request(1)
    prefix.decode(value)
    value["execution_schedule"][0][0]["context"]["is_new"] = False
    assert prefix.request["execution_schedule"][0][0]["context"]["is_new"] is True
    bar, account = data(1)
    before = deepcopy(prefix.request)
    for extra in [{}, dict(execution_passes=[]), dict(execution_schedule=[], execution_schedule_contract="unknown")]:
        with pytest.raises(ValueError, match="PINE_PREFIX_INVALID"):
            prefix.decode(dict(operation="append_prefix", prefix_base=1, bars=[bar], accounts=[account], **extra))
        assert prefix.request == before
