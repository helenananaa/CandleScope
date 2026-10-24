"""Realtime event plans cross actual physical books and historical V2 accounts."""
from decimal import Decimal
import os

import pytest

from tests.test_chart_book_snapshot import host as book_host,MODES
from tests.test_pine_event_realtime import SOURCE,event_worker

pytestmark=pytest.mark.skipif(not os.environ.get("PINE_EVENT_TEST_PYTHON"),reason="requires installed realtime event worker")


@pytest.mark.parametrize("mode",MODES)
def test_chart_book_event_windows_keep_exact_physical_account_costs_and_recovery(book_host,event_worker,tmp_path,monkeypatch,mode):
    from tests import test_chart_book_snapshot as fixtures
    from app.local_data.service import LocalImportOptions
    from app.backtest.strategy.pine_engine import PineEngineProvider
    from app.simulation.dual_clock_book import execution_type
    runtime,base=book_host
    runtime.worker.shutdown()
    service=runtime.service
    service._colocated_worker=True
    csv=tmp_path/"event-bars.csv"
    csv.write_text('time,open,high,low,close,volume\n'+'\n'.join(
        f'{i*60000},{p},{p+1},{p-1},{p},4' for i,p in enumerate((10,13,16))))
    manifest=runtime.local_data.import_csv(csv,LocalImportOptions(name="event book chart",symbol="BTCUSDT",interval="1m",timestamp_unit="ms"))
    base={**base,"dataset_id":manifest["dataset_id"],"data_epoch":manifest["data_epoch"]}
    original=fixtures.data
    def data(mode):
        result=original(mode)
        for ordinal,row in enumerate(result["events"]):
            payload=row["payload"]
            # Each quote immediately precedes its source print; derive the
            # bucket from stable physical pairs rather than the quote clock.
            index=ordinal//2
            offset=3*(index//4)
            if row["role"]=="TRADES":payload["price"]=str(Decimal(payload["price"])+offset)
            elif "bid" in payload:
                for side in ("bid","ask"):payload[side]=str(Decimal(payload[side])+offset)
            else:
                for side in ("bids","asks"):
                    for level in payload[side]:level[0]=str(Decimal(level[0])+offset)
        return result
    monkeypatch.setattr(fixtures,"data",data)
    value=fixtures.v2_config(runtime,base,mode,tmp_path)
    source=SOURCE.replace('if not na(x) and not sent','if n==1').replace(
        'if strategy.position_size>0','if bar_index==2 and barstate.isnew and strategy.position_size>0')
    source+='\nif syminfo.pointvalue!=50\n    runtime.error("wrong observed contract multiplier")\n'
    revision=service.create_strategy_revision(dict(name="V2 event book",language="PINE_ENGINE",source_text=source))
    value["strategy_revision_id"]=revision["revision_id"]
    service.smoke_strategy_revision(revision["revision_id"],value)
    _,events,_=fixtures.freeze(runtime,value)
    def execute(run):
        return service.execute_dual_clock_run(run["run_id"],events=events,provider=PineEngineProvider(),
            observation_market={"venue":"binance","market_type":"usdm","symbol":"BTCUSDT"})
    baseline=execute(service.create_run(value,idempotency_key="event-book-baseline"))
    assert baseline["report"]["cost_sensitivity"]["baseline_reexecution_verified"] is True
    assert baseline["report"]["account"]["funding_event_count"]==2
    assert all(Decimal(row["contract_multiplier"])==50 for row in baseline["report"]["fills"])
    assert [row["event_time_ms"] for row in baseline["report"]["fills"]]==[10000,130000]
    value["cost_sensitivity_mode"]="SKIP"
    # The report hash also binds the requested cost report; recovery compares
    # two runs with the same report settings after qualifying FULL separately.
    baseline=execute(service.create_run(value,idempotency_key="event-book-recovery-baseline"))
    run=service.create_run(value,idempotency_key="event-book-interrupted")
    original_save=service.repository.save_checkpoint
    def save(record):
        result=original_save(record)
        if record["sequence"]==8:raise KeyboardInterrupt("retained sealed event/book/account prefix")
        return result
    monkeypatch.setattr(service.repository,"save_checkpoint",save)
    with pytest.raises(KeyboardInterrupt):execute(run)
    monkeypatch.setattr(service.repository,"save_checkpoint",original_save)
    cls=execution_type(mode)
    original_restore,original_match=cls.restore,cls._match
    restored={}
    def restore(kernel,state):
        result=original_restore(kernel,state)
        restored[id(kernel)]=state["last_event"]["sequence"]
        return result
    def match(kernel,event):
        if id(kernel) in restored:assert event.sequence>restored[id(kernel)],"recorded physical source was rematched"
        return original_match(kernel,event)
    monkeypatch.setattr(cls,"restore",restore)
    monkeypatch.setattr(cls,"_match",match)
    assert service.requeue_interrupted_run(run["run_id"],expected_generation=1)
    recovered=execute(run)
    assert recovered["report"]["fills"]==baseline["report"]["fills"]
    assert recovered["report"]["hashes"]==baseline["report"]["hashes"]
    assert recovered["report"]["ledger"]==baseline["report"]["ledger"]
