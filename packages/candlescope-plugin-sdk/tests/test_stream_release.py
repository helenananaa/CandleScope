"""Optional stream release is explicit, negotiated and retryable."""
from dataclasses import replace

import pytest

from candlescope_plugin_sdk import (
    Bar, BaseRuntimePlugin, ExecuteBatchRequest, ExecuteBatchResult, LanguageDescriptor,
    MarketContext, ProtocolError, RenderOutput, RuntimeDescriptor, RuntimeDispatcher,
    FEATURE_BATCH_BARS_PATCH_V1, FEATURE_BATCH_EXECUTION_V1, FEATURE_RENDER_LINE_SERIES_V1,
    FEATURE_STREAM_RELEASE_V1, PROTOCOL_V1,
)


class Plugin(BaseRuntimePlugin):
    def __init__(self):
        self.released = []
        self.fail = False

    def describe(self):
        return RuntimeDescriptor(id='stream-owner', name='Stream owner', version='1.0', package='stream-owner',
            languages=(LanguageDescriptor(id='test', name='Test'),),
            required_host_features=(),
            features=(FEATURE_BATCH_EXECUTION_V1, FEATURE_RENDER_LINE_SERIES_V1,
                      FEATURE_BATCH_BARS_PATCH_V1, FEATURE_STREAM_RELEASE_V1))

    def analyze(self, _request): raise NotImplementedError

    def execute_batch(self, _request): return ExecuteBatchResult(ok=True, output=RenderOutput())

    def release_stream(self, stream):
        if self.fail: raise RuntimeError('durable release failed')
        self.released.append(stream)


def make_dispatcher(*, release=True):
    plugin = Plugin()
    dispatcher = RuntimeDispatcher(plugin)
    features = list(plugin.describe().features)
    if not release: features.remove(FEATURE_STREAM_RELEASE_V1)
    dispatcher.dispatch('handshake', {'protocols':[PROTOCOL_V1], 'host':{'name':'test', 'version':'1'},
                                    'hostFeatures':features})
    return plugin, dispatcher


def test_release_clears_only_named_base_after_plugin_ack_and_is_idempotent():
    plugin, dispatcher = make_dispatcher()
    request = ExecuteBatchRequest(source='test', context=MarketContext('binance', 'spot', 'BTCUSDT', '1m'),
        bars=(Bar(time=1700000000, open=1, high=2, low=1, close=2, volume=1),), bars_stream='first')
    dispatcher.dispatch('executeBatch', request.to_wire())
    dispatcher.dispatch('executeBatch', replace(request, bars_stream='other').to_wire())
    plugin.fail = True
    with pytest.raises(RuntimeError, match='durable release failed'):
        dispatcher.dispatch('releaseStream', {'stream':'first'})
    assert set(dispatcher._bars) == {'first', 'other'}
    plugin.fail = False
    assert dispatcher.dispatch('releaseStream', {'stream':'first'}) == {'stream':'first', 'released':True}
    assert set(dispatcher._bars) == {'other'}
    dispatcher.dispatch('releaseStream', {'stream':'first'})
    assert plugin.released == ['first', 'first']
    # Reusing the id starts a fresh full base; it never reuses a dropped prefix.
    dispatcher.dispatch('executeBatch', request.to_wire())
    assert set(dispatcher._bars) == {'first', 'other'}


def test_release_requires_feature_and_handshake_before_plugin_call():
    plugin, dispatcher = make_dispatcher(release=False)
    with pytest.raises(ProtocolError, match='not negotiated'):
        dispatcher.dispatch('releaseStream', {'stream':'first'})
    assert not plugin.released
    fresh = RuntimeDispatcher(plugin)
    with pytest.raises(ProtocolError, match='handshake'):
        fresh.dispatch('releaseStream', {'stream':'first'})


@pytest.mark.parametrize('params', [{}, {'stream':''}, {'stream':' '}, {'stream':'x'*129},
    {'stream':7}, {'stream':True}, {'stream':'first', 'all':True}])
def test_release_validates_one_bounded_explicit_stream(params):
    plugin, dispatcher = make_dispatcher()
    with pytest.raises(ProtocolError, match='stream'):
        dispatcher.dispatch('releaseStream', params)
    assert not plugin.released
