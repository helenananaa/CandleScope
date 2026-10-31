import pytest

from candlescope_plugin_sdk.platform_v2 import validate_provider_symbols_page, PlatformContractError


def page(**extra):
    symbol=dict(symbol="ABC",baseAsset="A",quoteAsset="USD",status="active",exchange="fixture",marketType="futures",
                productType="perpetual",priceTickSize="0.1",**extra)
    return dict(schemaVersion="candlescope.provider-symbols-page/1",exchange="fixture",marketType="futures",
                symbols=[symbol],nextCursor=None,exhausted=True,
                sourceQuality={"quality": "synthetic", "finality": "explicit", "timestamp": "provider"})


def test_provider_page_preserves_optional_contract_metadata():
    value=page(contractMultiplier="50",contractValueModel="linear",quantityStep=".25",minQuantity="2",
               quantityOrigin="0",quantityRuleModel="fixed_step")
    assert validate_provider_symbols_page(value)==value
    assert validate_provider_symbols_page(page())==page()


@pytest.mark.parametrize("field",["contractMultiplier","quantityStep","minQuantity"])
@pytest.mark.parametrize("value",["0","-1","NaN","Infinity",True])
def test_invalid_contract_numbers_have_specific_contract_paths(field,value):
    with pytest.raises(PlatformContractError) as error:
        validate_provider_symbols_page(page(**{field:value}))
    assert error.value.path.endswith("."+field)


@pytest.mark.parametrize("field,value",[("contractValueModel","linear-ish"),("quantityRuleModel","decimal_places"),
                                        ("quantityOrigin","-1"),("quantityStep",.25)])
def test_unknown_contract_profiles_and_non_decimal_types_are_rejected(field,value):
    with pytest.raises(PlatformContractError) as error:
        validate_provider_symbols_page(page(**{field:value}))
    assert error.value.path.endswith("."+field)
