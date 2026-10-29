from types import SimpleNamespace

import pytest

from app.backtest.pine_contract_metadata import catalog_chart_metadata, catalog_contract_profile
from app.exchanges.models import SymbolInfo
from app.indicator import pine_host_inputs


def catalog(**extra):
    return dict(priceTickSize="0.1",quoteAsset="USD",contractMultiplier="50",contractValueModel="linear",
                quantityStep=".25",minQuantity="2",quantityOrigin="0",quantityRuleModel="fixed_step",**extra)


def test_catalog_metadata_maps_contract_value_and_independent_minimum():
    assert catalog_chart_metadata(catalog())==dict(priceTickSize="0.1",currency="USD",pointValue=50.,quantityStep=".25",minContract="2")
    assert catalog_contract_profile(catalog())==dict(model="linear",quantityModel="fixed_step")
    explicit=dict(priceTickSize=".5",quantityPrecision=3)
    assert catalog_chart_metadata(catalog(),explicit)==dict(priceTickSize=".5",currency="USD",pointValue=50.,quantityStep=".25",minContract="2",quantityPrecision=3)


def test_indicator_options_keep_actual_catalog_fields_and_explicit_price(monkeypatch):
    monkeypatch.setattr(pine_host_inputs,"get_cached_symbol_metadata",lambda *args:catalog())
    result=pine_host_inputs.indicator_host_options(SimpleNamespace(exchange="fixture",market_type="futures",symbol="ABC"),
                                                 {"pineChartMetadata":{"priceTickSize":".5"}})
    assert result["pineChartMetadata"]==catalog_chart_metadata(catalog(),{"priceTickSize":".5"})
    assert result["pineContractProfile"]==dict(model="linear",quantityModel="fixed_step")


def test_catalog_profile_does_not_guess_a_zero_grid_for_offset_or_significant_rules():
    assert catalog_contract_profile({"quantityStep":".25","quantityOrigin":".3"})=={"quantityModel":"offset_step"}
    assert catalog_contract_profile({"quantityRuleModel":"significant_digits"})=={"quantityModel":"significant_digits"}
    assert catalog_contract_profile({"contractValueModel":"inverse"})=={"model":"inverse"}
    assert catalog_contract_profile({"quantityStep":".25","quantityOrigin":"0e1000000"})=={}
    with pytest.raises(ValueError):
        catalog_contract_profile({"quantityStep":".25","quantityOrigin":"1e1000000"})


@pytest.mark.parametrize("value",[True,"NaN","Infinity","-1","0","not-a-number","0.100000000000000001"])
def test_catalog_multiplier_fails_before_lossy_native_transport(value):
    with pytest.raises(ValueError):
        catalog_chart_metadata({"priceTickSize":"0.1","contractMultiplier":value})


def test_symbol_info_preserves_optional_quantity_fields_and_leaves_old_rows_compatible():
    kwargs=dict(price_tick_size="0.1",contract_multiplier="50",quantity_step=".25",min_quantity="2",
                quantity_origin="0",quantity_rule_model="fixed_step",contract_value_model="linear")
    value=SymbolInfo("ABC","A","USD","TRADING","fixture","futures","perpetual",**kwargs).to_dict()
    assert value["contractMultiplier"]=="50" and value["quantityStep"]==".25" and value["minQuantity"]=="2"
    assert value["quantityOrigin"]=="0" and value["quantityRuleModel"]=="fixed_step"
    old=SymbolInfo("ABC","A","USD","TRADING","fixture","spot","spot").to_dict()
    assert not {"quantityStep","minQuantity","quantityOrigin","quantityRuleModel","contractValueModel"}&old.keys()
