from dataclasses import replace

import pytest
from candlescope_plugin_pine_compat import PineCompatRuntimePlugin
from candlescope_plugin_pine_compat.currency_inputs import currency_rates
from candlescope_plugin_pine_compat.host_inputs import native_request_bars
from test_host_inputs import request, BARS

RATES = {"schemaVersion": 1, "pairs": [{"from": "USD", "to": "EUR", "rates": [
    {"effectiveTime": 0, "rate": 0.8}, {"effectiveTime": BARS[0].time * 1000 + 1, "rate": 0.9}]}]}


def test_indicator_effective_rates_do_not_read_future_frames_and_changed_provider_resets_session():
    plugin = PineCompatRuntimePlugin()
    req = request('plot(request.currency_rate("USD", "EUR"))', pineCurrencyRates=RATES, pineSessionId="fx")
    initial = plugin.execute_batch(req)
    assert initial.ok, initial.diagnostics
    assert initial.output.series[0].points[-1].value == 0.8
    changed = {"schemaVersion": 1, "pairs": [{"from": "USD", "to": "EUR", "rates": [{"effectiveTime": 0, "rate": 0.7}]}]}
    result = plugin.execute_batch(replace(req, options={**req.options, "pineCurrencyRates": changed}))
    assert result.ok, result.diagnostics
    assert result.meta["sessionReset"]
    assert result.output.series[0].points[-1].value == 0.7
    missing = plugin.execute_batch(request('plot(request.currency_rate("USD", "EUR"))'))
    assert not missing.ok


def test_quote_currency_is_explicit_and_native_replay_receives_same_provider():
    plugin = PineCompatRuntimePlugin()
    result = plugin.execute_batch(request('plot(syminfo.currency == "USDT" ? 1 : 0)', pineChartMetadata={"priceTickSize": ".1", "currency": "USDT"}))
    assert result.ok, result.diagnostics
    assert result.output.series[0].points[-1].value == 1
    missing = plugin.execute_batch(request('plot(syminfo.currency == "USDT" ? 1 : 0)', pineChartMetadata={"priceTickSize": ".1"}))
    assert not missing.ok
    assert missing.diagnostics[0].code == "PINE_HOST_METADATA_REQUIRED"
    supplied = native_request_bars({"context": {"metadata": {"priceTickSize": ".1", "currency": "USDT"}}, "currency_rates": RATES}, {})
    assert supplied["$chart"]["currency"] == "USDT"
    assert supplied["$currencyRates"] == RATES


@pytest.mark.parametrize("value", [
    {}, {"schemaVersion": True, "pairs": []},
    {"schemaVersion": 1, "pairs": [{"from": "usd", "to": "EUR", "rates": []}]},
    {"schemaVersion": 1, "pairs": RATES["pairs"] * 2},
    {"schemaVersion": 1, "pairs": [{"from": "USD", "to": "EUR", "unavailable": False}]},
    {"schemaVersion": 1, "pairs": [{"from": "USD", "to": "EUR", "rates": [{"effectiveTime": 0, "rate": True}]}]},
    {"schemaVersion": 1, "pairs": [{"from": "USD", "to": "EUR", "rates": [{"effectiveTime": 2, "rate": .8}, {"effectiveTime": 1, "rate": .7}]}]},
])
def test_invalid_rates_fail_instead_of_using_identity_or_a_different_pair(value):
    with pytest.raises(ValueError, match="PINE_CURRENCY_INPUT_INVALID"):
        currency_rates(value)


def test_imported_native_requirements_include_library_price_grid_usage():
    from candlescope_plugin_pine_compat.native_strategy import prepare
    source = '//@version=6\nstrategy("grid")\nimport local/Grid/1 as grid\nplot(grid.step(close))'
    library = '//@version=6\nlibrary("Grid")\nexport step(float x) => x + syminfo.mintick'
    with pytest.raises(ValueError, match="PINE_HOST_METADATA_REQUIRED"):
        prepare({"source": source, "libraries": {"local/Grid/1": library}})


def test_foreign_account_currency_needs_actual_metadata_and_cannot_relabel_host_ledger():
    from candlescope_plugin_pine_compat.native_strategy import prepare
    from candlescope_plugin_pine_compat.host_inputs import require_quote_currency
    import pine_compat
    source = '//@version=6\nstrategy("FX",currency=currency.EUR)'
    with pytest.raises(ValueError, match="actual quote currency"):
        prepare({"source": source, "context": {"symbol": "BINANCE:BTCUSDT", "timeframe": "1"}})
    analysis = pine_compat.analyze_script(source)
    requirements = pine_compat.compile_script(source).host_requirements()
    context = {"context": {"metadata": {"priceTickSize": ".1", "currency": "USDT"}}}
    require_quote_currency(analysis, requirements, context)
    with pytest.raises(ValueError, match="does not convert account currencies"):
        require_quote_currency(analysis, requirements, context, external=True)
