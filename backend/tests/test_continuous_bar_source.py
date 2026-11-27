"""Actual canonical-to-frozen-to-tail ownership across financial restarts."""
from dataclasses import asdict

import pytest

from app.backtest.continuous_bar_host import ContinuousBarHost
from app.backtest.continuous_bar_source import ContinuousMarketBarSource
from app.backtest.continuous_store import ContinuousStrategyStore
from app.backtest.errors import BacktestError
from app.backtest.identity import canonical_json
from app.data_engine.data_manager import DataManager
from app.data_engine.data_manager.models import SeriesKey
from app.data_engine.storage import klines_repo
from app.data_engine.storage.prefix_watches import PrefixAcquisitionChanged,ProcessedPrefixChanged
from app.local_data.service import LocalDatasetService
from app.market_dataset.snapshot import MarketEvent
from tests.test_kline_revision_contract import storage as storage
from tests.test_continuous_bar_host import prepare
from tests.test_continuous_guarded_source import KEY,START,STEP,END,SOURCE,_row

DATASET = "local-"+"a"*32


def source_setup(storage,tmp_path,monkeypatch):
    service,row,definition,factory,store = prepare(tmp_path,monkeypatch)
    manager=DataManager();manager.set_storage(storage)
    klines_repo.upsert_klines(KEY.symbol,KEY.interval,[_row(START+i*STEP,100+i%7) for i in range(25)],source=SOURCE)
    local=LocalDatasetService(tmp_path/'local-data')
    source=ContinuousMarketBarSource(manager,local,KEY,clock_ms=lambda:END+1)
    receipt=source.register("cs_source",from_ms=START)
    definition.update(source_kind="MARKET_BAR",source_series=list(receipt.series),market={"venue":"binance","symbol":KEY.symbol})
    return service,row,definition,factory,store,manager,source,receipt


def create_frozen(source,receipt,definition,factory,store,*,through=START+20*STEP-1):
    sealed=source.freeze_initial(receipt,through_ms=through,dataset_id=DATASET)
    definition={**definition,"initial_snapshot":sealed.descriptor}
    ContinuousBarHost.create_run(store,"cs_source",definition=definition,mode="HISTORY_LIVE",
        data_revision=receipt.incarnation,event_time_ms=receipt.through_ms,provider_factory=factory,
        source_receipt=sealed.receipt,commit_checkpoint=lambda publish:source.manager.bars.prefixes.commit(
            sealed.proof,publish,committed_through_ms=receipt.through_ms))
    return definition


def test_sealed_initial_input_restart_and_tail_equal_fixed_financial_reference(storage,tmp_path,monkeypatch):
    service,row,definition,factory,store,manager,source,receipt=source_setup(storage,tmp_path,monkeypatch)
    host=None
    try:
        definition=create_frozen(source,receipt,definition,factory,store)
        host=ContinuousBarHost.resume(store,"cs_source",factory)
        first=source.acquire(host,revealed_through_ms=END,limit=7)
        assert not first.caught_up and len(first.events)==7
        first.apply(host,manager)
        assert host.row["sequence"]==7 and host.row["phase"]=="CATCHING_UP"
        host.close();source.close();store.close()
        store=ContinuousStrategyStore(tmp_path/'continuous.db')
        source=ContinuousMarketBarSource(manager,LocalDatasetService(tmp_path/'local-data'),KEY,clock_ms=lambda:END+1)
        host=ContinuousBarHost.resume(store,"cs_source",factory)
        second=source.acquire(host,revealed_through_ms=END)
        assert len(second.events)==13 and second.events[-1].event_time_ms==START+20*STEP-1
        assert not second.caught_up
        second.apply(host,manager)
        tail=source.acquire(host,revealed_through_ms=END)
        assert len(tail.events)==5 and tail.caught_up
        tail.apply(host,manager)
        assert host.row["phase"]=="LIVE" and host.row["sequence"]==25
        assert source._reader is None
        actual=asdict(host.kernel.run((),host._observe,finalize=True))
        all_rows=source._query_rows(START,END,tail.proof.storage_revision)
        events=tuple(MarketEvent(i+1,r["close_time_ms"],"BARS",r) for i,r in enumerate(all_rows))
        reference=service.execute_bar_run(row["run_id"],events=events,provider=factory(definition),
            observation_market=definition["market"],now_ms=3)["result"]
        for field in ("decision_hash","fill_hash","ledger_hash","fills","orders","ledger","equity_curve"):
            assert canonical_json(actual[field])==canonical_json(reference[field]),field
        assert actual["fills"]
    finally:
        if host is not None:host.close()
        source.close();store.close();service.shutdown()


def test_initial_source_change_during_provider_preparation_cannot_create_account(storage,tmp_path,monkeypatch):
    service,_,definition,factory,store,manager,source,receipt=source_setup(storage,tmp_path,monkeypatch)
    def changed(value):
        klines_repo.upsert_klines(KEY.symbol,KEY.interval,[_row(START+15*STEP,220)],source=SOURCE)
        return factory(value)
    try:
        with pytest.raises(PrefixAcquisitionChanged):create_frozen(source,receipt,definition,changed,store)
        with pytest.raises(BacktestError,match="Unknown continuous"):
            store.summary("cs_source")
        assert manager.bars.prefixes.inspect(receipt.owner)["committed_acquisition"]==0
    finally:source.close();store.close();service.shutdown()


def test_unprocessed_initial_suffix_change_rejected_before_reading_next_page(storage,tmp_path,monkeypatch):
    service,_,definition,factory,store,manager,source,receipt=source_setup(storage,tmp_path,monkeypatch)
    host=None
    try:
        create_frozen(source,receipt,definition,factory,store)
        host=ContinuousBarHost.resume(store,"cs_source",factory)
        source.acquire(host,revealed_through_ms=END,limit=7).apply(host,manager)
        before=store.load("cs_source")
        klines_repo.upsert_klines(KEY.symbol,KEY.interval,[_row(START+15*STEP,220)],source=SOURCE)
        with pytest.raises(ProcessedPrefixChanged):source.acquire(host,revealed_through_ms=END)
        assert store.load("cs_source")==before
    finally:
        if host is not None:host.close()
        source.close();store.close();service.shutdown()


def test_live_only_starts_at_frozen_first_cursor_and_rechecks_revisions_without_new_bar(storage,tmp_path,monkeypatch):
    service,_,definition,factory,store,manager,source,receipt=source_setup(storage,tmp_path,monkeypatch)
    host=None
    # A separate identity starts after the initial 20 rows, not from chart history.
    live=source.register("cs_live",from_ms=START+20*STEP)
    try:
        ContinuousBarHost.create_run(store,"cs_live",definition=definition,mode="LIVE_ONLY",
            data_revision=live.incarnation,event_time_ms=live.through_ms,provider_factory=factory,source_receipt=live)
        host=ContinuousBarHost.resume(store,"cs_live",factory)
        batch=source.acquire(host,revealed_through_ms=END)
        assert len(batch.events)==5 and batch.events[0].payload["open_time_ms"]==START+20*STEP
        batch.apply(host,manager)
        assert host.row["sequence"]==5
        klines_repo.upsert_klines(KEY.symbol,KEY.interval,[_row(START+20*STEP,220)],source=SOURCE)
        with pytest.raises(ProcessedPrefixChanged):source.acquire(host,revealed_through_ms=END)
    finally:
        if host is not None:host.close()
        source.close();store.close();service.shutdown()


def test_revealed_boundary_cannot_admit_forming_or_future_input(storage,tmp_path,monkeypatch):
    service,_,definition,factory,store,_,source,receipt=source_setup(storage,tmp_path,monkeypatch)
    try:
        for boundary in (END+STEP,END-1):
            with pytest.raises(BacktestError,match="LOOKAHEAD_VIOLATION"):
                source.freeze_initial(receipt,through_ms=boundary,dataset_id=DATASET)
        assert source.local_datasets.list_datasets()==[]
    finally:source.close();store.close();service.shutdown()


def test_live_only_initially_empty_confirms_ready_once_and_restart_keeps_same_account(storage,tmp_path,monkeypatch):
    service,_,definition,factory,store,manager,source,_=source_setup(storage,tmp_path,monkeypatch)
    host=None
    live=source.register("cs_empty",from_ms=END+1)
    try:
        ContinuousBarHost.create_run(store,"cs_empty",definition=definition,mode="LIVE_ONLY",
            data_revision=live.incarnation,event_time_ms=END,provider_factory=factory,source_receipt=live)
        host=ContinuousBarHost.resume(store,"cs_empty",factory)
        before=host.checkpoint()
        batch=source.acquire(host,revealed_through_ms=END)
        assert not batch.events
        batch.apply(host,manager)
        assert host.row["phase"]=="LIVE" and host.row["sequence"]==0
        for key in ("engine","provider","planner"):
            assert host.checkpoint()[key]==before[key]
        checkpoint_revision=host.row["checkpoint_revision"]
        for _ in range(3):source.acquire(host,revealed_through_ms=END).apply(host,manager)
        assert host.row["checkpoint_revision"]==checkpoint_revision
        host.close()
        host=ContinuousBarHost.resume(store,"cs_empty",factory)
        source.acquire(host,revealed_through_ms=END).apply(host,manager)
        assert host.row["phase"]=="LIVE" and host.row["sequence"]==0
        assert host.checkpoint()["provider"]["generation"]==before["provider"]["generation"]+1
        before["provider"]["generation"]+=1
        for key in ("engine","provider","planner"):
            assert host.checkpoint()[key]==before[key]
    finally:
        if host is not None:host.close()
        source.close();store.close();service.shutdown()


def test_initial_copy_queries_bounded_pages_and_excludes_future_extreme(storage,tmp_path,monkeypatch):
    service,_,_,_,store,manager,source,receipt=source_setup(storage,tmp_path,monkeypatch)
    last=START+1005*STEP-1
    source.clock_ms=lambda:last+1
    klines_repo.upsert_klines(KEY.symbol,KEY.interval,
        [_row(START+i*STEP,101) for i in range(25,1005)]+[_row(START+1005*STEP,999999)],source=SOURCE)
    query=manager.bars.query;windows=[]
    def observed(*args,**kwargs):
        windows.append((kwargs["start_ms"],kwargs["end_ms"],kwargs["limit"]))
        return query(*args,**kwargs)
    monkeypatch.setattr(manager.bars,"query",observed)
    try:
        sealed=source.freeze_initial(receipt,through_ms=last,dataset_id=DATASET)
        assert windows==[(START,START+999*STEP,1000),(START+1000*STEP,START+1004*STEP,5)]
        with source.local_datasets.open_pinned_bar_window(DATASET,data_epoch=sealed.descriptor["data_epoch"],
                interval="1m",from_ms=START,through_ms=last) as reader:
            tail=reader.read_window(start_ms=START+1000*STEP)
            assert len(tail)==5 and all(row["close"]=="101" for row in tail)
            assert reader.read_window(start_ms=START+1005*STEP)==[]
    finally:source.close();store.close();service.shutdown()


FIVE = SeriesKey("BTCUSDT", "5m")
FIVE_STEP = 300_000
FIVE_START = (START // FIVE_STEP + 1) * FIVE_STEP
FIVE_END = FIVE_START + 25 * FIVE_STEP - 1


def five_minute_setup(storage, tmp_path, monkeypatch):
    service, row, definition, factory, store = prepare(tmp_path, monkeypatch)
    manager = DataManager();manager.set_storage(storage)
    klines_repo.upsert_klines(FIVE.symbol, FIVE.interval, [
        {**_row(FIVE_START + i * FIVE_STEP, 100 + i % 7), "close_time": FIVE_START + (i + 1) * FIVE_STEP - 1}
        for i in range(25)], source=SOURCE)
    source = ContinuousMarketBarSource(manager, LocalDatasetService(tmp_path / 'local-data'), FIVE,
                                       clock_ms=lambda: FIVE_END + 1)
    receipt = source.register("cs_source", from_ms=FIVE_START)
    definition.update(source_kind="MARKET_BAR", source_series=list(receipt.series),
                      market={"venue": "binance", "symbol": FIVE.symbol})
    return service, row, definition, factory, store, manager, source, receipt


def test_a_5m_forward_run_restarts_and_equals_the_fixed_run_of_its_bars(storage, tmp_path, monkeypatch):
    """B-333: a forward run advances on closed bars of its own signal interval."""
    service, row, definition, factory, store, manager, source, receipt = five_minute_setup(storage, tmp_path, monkeypatch)
    host = None
    try:
        definition = create_frozen(source, receipt, definition, factory, store, through=FIVE_START + 20 * FIVE_STEP - 1)
        host = ContinuousBarHost.resume(store, "cs_source", factory)
        first = source.acquire(host, revealed_through_ms=FIVE_END, limit=7)
        assert len(first.events) == 7 and [event.payload["close_time_ms"] - event.payload["open_time_ms"]
                                           for event in first.events] == [FIVE_STEP - 1] * 7
        first.apply(host, manager)
        host.close();source.close();store.close()
        store = ContinuousStrategyStore(tmp_path / 'continuous.db')
        source = ContinuousMarketBarSource(manager, LocalDatasetService(tmp_path / 'local-data'), FIVE,
                                           clock_ms=lambda: FIVE_END + 1)
        host = ContinuousBarHost.resume(store, "cs_source", factory)
        rest = source.acquire(host, revealed_through_ms=FIVE_END)
        assert len(rest.events) == 13 and not rest.caught_up  # the sealed initial bars end at bar 20
        rest.apply(host, manager)
        tail = source.acquire(host, revealed_through_ms=FIVE_END)
        assert len(tail.events) == 5 and tail.caught_up
        tail.apply(host, manager)
        assert host.row["phase"] == "LIVE" and host.row["sequence"] == 25 and host.row["event_time_ms"] == FIVE_END
        actual = asdict(host.kernel.run((), host._observe, finalize=True))
        rows = source._query_rows(FIVE_START, FIVE_END, rest.proof.storage_revision)
        events = tuple(MarketEvent(i + 1, r["close_time_ms"], "BARS", r) for i, r in enumerate(rows))
        reference = service.execute_bar_run(row["run_id"], events=events, provider=factory(definition),
                                            observation_market=definition["market"], now_ms=3)["result"]
        for field in ("decision_hash", "fill_hash", "ledger_hash", "fills", "orders", "ledger", "equity_curve"):
            assert canonical_json(actual[field]) == canonical_json(reference[field]), field
        assert actual["fills"]
    finally:
        if host is not None:host.close()
        source.close();store.close();service.shutdown()


def test_a_5m_source_admits_only_its_own_bar_boundaries(storage, tmp_path, monkeypatch):
    service, _row_, definition, factory, store, manager, source, receipt = five_minute_setup(storage, tmp_path, monkeypatch)
    try:
        with pytest.raises(BacktestError) as early:
            source.register("cs_other", from_ms=FIVE_START + 60_000)
        assert early.value.code == "CONTINUOUS_SOURCE_GAP"
        create_frozen(source, receipt, definition, factory, store, through=FIVE_START + 20 * FIVE_STEP - 1)
        host = ContinuousBarHost.resume(store, "cs_source", factory)
        try:
            # A 1m close inside a 5m bar is not a boundary of this run.
            with pytest.raises(BacktestError) as inside:
                source.acquire(host, revealed_through_ms=FIVE_START + 20 * FIVE_STEP + 60_000 - 1)
            assert inside.value.code == "LOOKAHEAD_VIOLATION"
            # Nor is a bar that has not closed yet.
            with pytest.raises(BacktestError) as future:
                source.acquire(host, revealed_through_ms=FIVE_END + FIVE_STEP)
            assert future.value.code == "LOOKAHEAD_VIOLATION"
        finally:
            host.close()
    finally:
        source.close();store.close();service.shutdown()
