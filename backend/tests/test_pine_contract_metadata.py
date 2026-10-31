from decimal import Decimal as D

import pytest
from pydantic import ValidationError

from app.backtest.errors import BacktestError
from app.backtest.native_contracts import PineChartMetadata
from app.backtest.pine_contract_metadata import bind_account_metadata
from tests.test_backtest_account_v2_m4 import ready
from tests.test_contract_quantity_rules import contract


@pytest.mark.parametrize('step',['0.25','2e-12','1e-18','+0.2500','25e-2'])
def test_contract_metadata_accepts_exact_decimal_rules_and_positive_multipliers(step):
    model=PineChartMetadata(priceTickSize='.1',pointValue=50,quantityStep=step,minContract='2')
    assert model.pointValue==50 and model.quantityStep==step and model.minContract=='2'


@pytest.mark.parametrize('field',['quantityStep','minContract'])
@pytest.mark.parametrize('value',[True,.25,'0','-1','NaN','1/4','1e-19','1e100000000000000000000','0.100000000000000001'])
def test_metadata_rejects_rules_that_cannot_cross_the_native_transport(field,value):
    with pytest.raises((ValidationError,ValueError),match=field):
        PineChartMetadata.model_validate(dict(priceTickSize='.1',**{field:value}))


def test_precision_is_a_separate_compatible_bound():
    assert PineChartMetadata(priceTickSize='.1',quantityStep='.25',quantityPrecision=2)
    with pytest.raises(ValidationError,match='quantityPrecision'):
        PineChartMetadata(priceTickSize='.1',quantityStep='.25',quantityPrecision=1)


def test_actual_account_rules_are_bound_and_conflicting_explicit_values_are_rejected():
    account=ready();account.apply(contract(multiplier='50',minimum='2'))
    metadata=bind_account_metadata(account,{'currency':'USD'})
    assert bind_account_metadata(account,{'priceTickSize':'1/10'})['priceTickSize']=='0.1'
    assert metadata==dict(priceTickSize='0.1',pointValue=50.,quantityStep='0.25',minContract='2',currency='USD')
    for field,wrong in [('pointValue',1),('quantityStep','.5'),('minContract','1'),('priceTickSize','.25')]:
        with pytest.raises(BacktestError) as error:
            bind_account_metadata(account,{field:wrong})
        assert error.value.code=='DATA_SNAPSHOT_MISMATCH'
    assert account.multiplier==D(50)
