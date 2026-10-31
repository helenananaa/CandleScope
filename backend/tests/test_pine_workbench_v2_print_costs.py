from decimal import Decimal as D

import pytest
from tests.test_native_backtests import runtime as runtime, terminal, pytestmark as pytestmark
from tests.test_pine_workbench_v2_print import config


@pytest.mark.parametrize("mode,participation",[("TRADE_TAPE",None),("TRADE_TAPE",.2),("BOOK_ASSISTED",None),("BOOK_DEPTH",None),("BOOK_SAMPLED",None)])
def test_v2_physical_costs_reexecute_independent_historical_accounts(runtime,mode,participation):
    host,main=runtime
    value=config(main,mode,True)
    value["cost_sensitivity_mode"]="AUTO"
    if participation is not None:
        value.update(execution_model_revision="EXECUTION_REALISM_V2",participation_rate=participation)
    record=terminal(host.native,host.native.create(value,"physical-costs")["run_id"])
    assert record["state"]=="COMPLETED",record.get("error")
    result=record["result"]
    matrix=result["cost_sensitivity"]
    assert matrix["baseline_reexecution_verified"] is True
    rows={row["name"]:row for row in matrix["scenarios"]}
    assert len(rows)==5
    assert rows["LATENCY_PLUS_ONE_TIER"]["status"]=="NOT_APPLICABLE_WORKBENCH_LATENCY_CONTRACT"
    assert rows["LATENCY_PLUS_ONE_TIER"]["executed"] is False
    for name in ("BASELINE","COSTS_PLUS_25_PERCENT","COSTS_PLUS_50_PERCENT"):
        assert rows[name]["executed"] is True
    assert rows["BASELINE"]["hashes"]["ledger"]!=rows["COSTS_PLUS_25_PERCENT"]["hashes"]["ledger"]
    assert rows["PARTICIPATION_DOWN_ONE_TIER"]["executed"] is (participation is not None)
    assert D(result["position"]["mark_price"])==13
    assert result["position"]["funding_event_count"]==1
    if participation is not None:
        from app.simulation.execution_realism import TRADE_FILL_POLICY_V2
        assert result["fill_model"] == TRADE_FILL_POLICY_V2
        assert result["raw_output"]["kernel"]["decision_hash"] != "sha256:GENESIS"
        assert result["raw_output"]["kernel"]["ledger"]["decision_count"] > 0
        assert max(D(row["qty"]) for row in result["trades"])<=D('5')


@pytest.mark.parametrize("callbacks",[False,True])
def test_v2_trade_participation_decision_chain_survives_real_account_restart(runtime,callbacks):
    from tests.test_native_replay import settle
    from app.simulation.execution_realism import TRADE_FILL_POLICY_V2
    host,main=runtime
    value=config(main,"TRADE_TAPE",callbacks)
    value.update(execution_model_revision="EXECUTION_REALISM_V2",participation_rate=.2)
    record=terminal(host.native,host.native.create(value,"physical-realism-recovery")["run_id"])
    assert record["state"]=="COMPLETED",record.get("error")
    result=record["result"]
    assert result["fill_model"]==TRADE_FILL_POLICY_V2
    assert result["raw_output"]["kernel"]["decision_hash"]!="sha256:GENESIS"
    assert result["raw_output"]["kernel"]["ledger"]["decision_count"]>=10
    replay=host.native.replay
    created=replay.create(record["run_id"]); key=created["replay_id"]
    def seek(target):
        replay.command(key,replay.get(key)["revision"],"seek",target)
        state=settle(replay,key)
        assert state.get("error") is None,state
        return state
    first=seek(1)
    snapshot=replay.snapshot(key,first["revision"])["snapshots"][0]["snapshot_id"]
    seek(3)
    replay.restore(key,replay.get(key)["revision"],snapshot)
    assert seek(created["total"])["result"]==result
