import pytest
from candlescope_plugin_pine_compat.host_inputs import require_price_grid, indicator_request_bars


@pytest.mark.parametrize("profile",[{"model":"inverse"},{"model":"unknown"},{"quantityModel":"significant_digits"},
                                    {"quantityModel":"offset_step"},{"quantityModel":"unknown"}])
def test_physical_profile_is_not_silently_used_as_linear_zero_aligned_strategy(profile):
    request={"context":{"metadata":{"priceTickSize":".1","pointValue":50,"quantityStep":".25"},"contract_profile":profile}}
    with pytest.raises(ValueError,match="PINE_HOST_METADATA_UNSUPPORTED"):
        require_price_grid({"scriptMode":"strategy"},request)
    require_price_grid({"scriptMode":"indicator"},request)


def test_known_physical_contract_requires_its_real_point_value_and_quantity_grid():
    request={"context":{"contract_profile":{"model":"linear"},"metadata":{"priceTickSize":".1"}}}
    with pytest.raises(ValueError,match="multiplier"):
        require_price_grid({"scriptMode":"strategy"},request)
    request["context"]["metadata"]["pointValue"]=50
    with pytest.raises(ValueError,match="quantity grid"):
        require_price_grid({"scriptMode":"strategy"},request)
    request["context"]["metadata"]["quantityPrecision"]=0
    require_price_grid({"scriptMode":"strategy"},request)


def test_missing_known_requested_point_value_cannot_use_synthetic_one():
    analysis={"scriptMode":"indicator","compatibility":{"supported":[{"feature":"syminfo.pointvalue"}]}}
    options={"pineRequestSymbolProfiles":{"OTHER":{"model":"linear"}}}
    with pytest.raises(ValueError,match="requested point value"):
        indicator_request_bars(analysis,options,"CHART",{"OTHER:1":[]})
