"""Real acquisition/adapter/native lifecycle for observed requested prefixes."""
from dataclasses import replace
from types import SimpleNamespace

import pine_compat
import pytest
from candlescope_plugin_sdk import AnalyzeRequest, Bar, ExecuteBatchRequest, MarketContext
from candlescope_plugin_pine_compat import PineCompatRuntimePlugin
from candlescope_plugin_pine_compat.session_requests import CONTRACT, observation_clock
from app.indicator.pine_host_inputs import requested_data


def test_observation_negotiation_validates_exact_clocks_and_preserves_old_core_fallback():
    value={"contract":CONTRACT,"observedAtMs":1000}
    assert observation_clock(SimpleNamespace(REALTIME_REQUEST_FEED_SCHEMA_VERSION=1),value)==1000
    for capability in [None,0,True,2]:
        assert observation_clock(SimpleNamespace(REALTIME_REQUEST_FEED_SCHEMA_VERSION=capability),value) is None
    for bad in [True,{},value|{"contract":"unknown"},value|{"observedAtMs":True},value|{"observedAtMs":-1},value|{"extra":1}]:
        with pytest.raises(ValueError,match="observation contract and clock"):
            observation_clock(pine_compat,bad)


installed=pytest.mark.skipif(getattr(pine_compat,"REALTIME_REQUEST_FEED_SCHEMA_VERSION",None)!=1,
    reason="requires installed provider-only feed API")


def fixture():
    plugin=PineCompatRuntimePlugin()
    source='//@version=6\nindicator("Observed requests")\nvarip int n=0\nn+=1\nplot(n)\nplot(array.size(request.security_lower_tf("OKX:ETH-USDT","1",close)))'
    chart=tuple(Bar(time=300+i*300,open=10,high=10,low=10,close=10,volume=1) for i in range(4))
    request=ExecuteBatchRequest(source=source,context=MarketContext("binance","spot","BTCUSDT","5m"),
        bars=chart[:2]+(replace(chart[2],is_closed=False),),options={"pineSessionId":"observed"})
    remote=[replace(chart[0],time=300+i*60,open=i,high=i,low=i,close=i) for i in range(20)]
    requirements=plugin.analyze(AnalyzeRequest(source=source,context=request.context)).meta["hostRequirements"]
    def compute(value,clock,*,raw=None):
        value=replace(value,options={**value.options,"pineExecutionTimeMs":clock,"pineRevealedBoundaryMs":clock})
        supplied=requested_data(value,requirements,SimpleNamespace(query=lambda *a,**k:SimpleNamespace(bars=remote,missing_ranges=[])))
        assert supplied["pineRequestObservation"]=={"contract":CONTRACT,"observedAtMs":clock}
        return plugin.execute_batch(replace(value,options={**value.options,**supplied,**(raw or {})}))
    return plugin,request,chart,remote,compute


def values(result):
    assert result.ok,result.diagnostics
    return [series.points[-1].value for series in result.output.series]


@installed
def test_new_requested_rows_preserve_varip_and_execute_exactly_once_through_confirmation():
    plugin,request,chart,_,compute=fixture()
    first=compute(request,1019999)
    assert values(first)==[3,2] and first.meta["sessionReset"]
    assert first.meta["requestedObservationContract"]==CONTRACT
    later=compute(request,1079999)
    assert values(later)==[4,3] and not later.meta["sessionReset"]
    repeat=compute(request,1079999)
    assert values(repeat)==[5,3] and not repeat.meta["sessionReset"]
    confirmed=compute(replace(request,bars=chart[:3]),1199999)
    assert values(confirmed)==[6,5] and not confirmed.meta["sessionReset"]
    following=compute(replace(request,bars=chart[:3]+(replace(chart[3],is_closed=False),)),1259999)
    assert values(following)==[7,1] and not following.meta["sessionReset"]
    isolated=compute(replace(request,options={"pineSessionId":"independent"}),1079999)
    assert values(isolated)==[3,3] and isolated.meta["sessionReset"]
    plugin.shutdown()


@installed
@pytest.mark.parametrize("change",["correction","truncation"])
def test_changed_requested_history_rebases_instead_of_reusing_a_different_prefix(change):
    _,request,_,remote,compute=fixture()
    assert values(compute(request,1019999))==[3,2]
    assert values(compute(request,1079999))==[4,3]
    if change=="correction":
        remote[0]=replace(remote[0],open=99,high=99,low=99,close=99)
    else:
        del remote[0]
    rebased=compute(request,1079999)
    assert rebased.ok,rebased.diagnostics
    assert rebased.meta["sessionReset"]
    assert values(rebased)[0]==3


@installed
def test_future_requested_row_is_rejected_and_failed_session_is_discarded():
    plugin,request,_,_,compute=fixture()
    assert values(compute(request,1019999))==[3,2]
    key="OKX:ETH-USDT:1"
    entry=plugin._sessions.entries["observed"]
    rows=[dict(row) for row in entry.requested[key]]
    rows.append({**rows[-1],"time":1080000})
    rejected=compute(request,1079999,raw={"pineRequestBars":{key:rows}})
    assert not rejected.ok
    assert "observed" not in plugin._sessions.entries
    restored=compute(request,1079999)
    assert values(restored)==[3,3] and restored.meta["sessionReset"]


@installed
def test_new_confirmed_higher_timeframe_row_can_open_before_the_current_chart_bar():
    plugin=PineCompatRuntimePlugin()
    source='//@version=6\nindicator("Higher observations")\nvarip int n=0\nn+=1\nplot(n)\nplot(request.security("OKX:ETH-USDT","15",close))'
    chart=tuple(Bar(time=900+i*300,open=10,high=10,low=10,close=10,volume=1) for i in range(6))
    request=ExecuteBatchRequest(source=source,context=MarketContext("binance","spot","BTCUSDT","5m"),
        bars=chart[:-1]+(replace(chart[-1],is_closed=False),),options={"pineSessionId":"higher"})
    remote=[replace(chart[0],time=time,open=price,high=price,low=price,close=price) for time,price in [(900,10),(1800,20)]]
    requirements=plugin.analyze(AnalyzeRequest(source=source,context=request.context)).meta["hostRequirements"]
    def compute(clock):
        value=replace(request,options={**request.options,"pineExecutionTimeMs":clock,"pineRevealedBoundaryMs":clock})
        supplied=requested_data(value,requirements,SimpleNamespace(query=lambda *a,**k:SimpleNamespace(bars=remote,missing_ranges=[])))
        return plugin.execute_batch(replace(value,options={**value.options,**supplied}))
    assert values(compute(2459999))==[6,10]
    later=compute(2699999)
    assert values(later)==[7,20] and not later.meta["sessionReset"]
