"""Actual engine boundary: repeated source time, distinct ordinal, external account."""
from copy import deepcopy
import pytest
import pine_compat
from candlescope_plugin_pine_compat import external_strategy as adapter
from test_external_incremental import data, wire

pytestmark=pytest.mark.skipif(getattr(pine_compat,'EXTERNAL_ORDERED_CHART_SCHEMA_VERSION',0)!=1,reason='requires ordered strategy engine')


@pytest.mark.parametrize('transform',['heikin-ashi','renko','point-and-figure','kagi','line-break'])
def test_ordered_strategy_keeps_bar_index_source_clock_and_host_account(transform):
    request=wire('plot(close)\nplot(ta.sma(close,2))\nplot(bar_index)\nplot(time)\nplot(strategy.position_size)\nif bar_index == 1\n    strategy.entry("L",strategy.long,qty=1)')
    bars=[];accounts=[]
    for i in range(3):
        bar,account=data(i);bar['time']=1700000000;account['time']=bar['time'];bars.append(bar);accounts.append(account)
    request.update(bars=bars,accounts=accounts,chart_signal_contract='ordered-chart-strategy/1',signal_chart={'transform':transform})
    result=adapter.execute(request)
    assert result['raw_output'].get('strategy') is None
    assert [row['bar_index'] for row in result['intents']]==[1]
    plots=result['raw_output']['plots']
    assert plots[0]['values']==[10.,11.,12.]
    assert plots[1]['values']==[None,10.5,11.5]
    assert plots[2]['values']==[0.,1.,2.]
    assert plots[3]['values']==[1700000000000.]*3
    assert plots[4]['values']==[0.,0.,0.]
    ordinary=deepcopy(request);ordinary.pop('chart_signal_contract');ordinary.pop('signal_chart')
    with pytest.raises(ValueError,match='duplicate bar time'):adapter.execute(ordinary)


def test_explicit_standard_symbol_request_keeps_market_context_separate_from_chart_bricks():
    request=wire('plot(close)\nplot(request.security("BINANCE:BTCUSDT", "1", close))')
    bar,account=data(0)
    request.update(bars=[bar],accounts=[account],chart_signal_contract='ordered-chart-strategy/1',signal_chart={'transform':'renko'},
        contexts=[{'symbol':'BINANCE:BTCUSDT','timeframe':'1','bars':[{**bar,'open':500,'high':501,'low':499,'close':500}]}])
    result=adapter.execute(request)
    assert result['raw_output']['plots'][0]['values']==[10.]
    assert result['raw_output']['plots'][1]['values']==[500.]
