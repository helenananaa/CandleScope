from types import SimpleNamespace

import pytest

from app.exchanges.contract_rules import binance_contract_rules, okx_contract_rules, ccxt_contract_rules, precision_increment


def test_binance_uses_lot_filter_and_keeps_minimum_separate_from_increment():
    result = binance_contract_rules(dict(filters=[dict(filterType='LOT_SIZE', stepSize='.25', minQty='2')], quantityPrecision=6))
    assert result == dict(contract_multiplier='1', contract_value_model='linear', quantity_step='.25',
                          min_quantity='2', quantity_origin='2', quantity_rule_model='fixed_step')


@pytest.mark.parametrize('model',['linear','inverse'])
def test_okx_preserves_contract_unit_and_contract_count_quantity_rules(model):
    result=okx_contract_rules(dict(ctType=model,ctVal='.01',ctMult='100',lotSz='.25',minSz='2',tickSz='.1'),spot=False)
    assert result['contract_multiplier']=='.01'
    assert result['contract_value_model']==model
    assert result['quantity_step']=='.25' and result['min_quantity']=='2'
    assert result['price_tick_size']=='.1'


@pytest.mark.parametrize('mode,value,expected',[(4,'.25','.25'),(2,3,'.001'),(2,-2,'100'),(3,8,''),(2,1.5,''),(4,True,''),(4,'NaN','')])
def test_precision_modes_are_not_conflated(mode,value,expected):
    actual=precision_increment(mode,value,tick_mode=4,decimal_mode=2)
    assert not actual if not expected else float(actual)==float(expected)


def test_ccxt_multiplier_and_minimum_survive_without_guessing_a_fixed_significant_grid():
    market=dict(linear=True,contractSize=50,precision=dict(amount=.25),limits=dict(amount=dict(min=2)))
    result=ccxt_contract_rules(SimpleNamespace(precisionMode=4),market,tick_mode=4,decimal_mode=2,significant_mode=3)
    assert result['contract_multiplier']=='50'
    assert result['quantity_step']=='0.25' and result['min_quantity']=='2'
    result=ccxt_contract_rules(SimpleNamespace(precisionMode=3),market,tick_mode=4,decimal_mode=2,significant_mode=3)
    assert result['quantity_step']=='' and result['quantity_rule_model']=='significant_digits'


def test_missing_grid_is_explicit_instead_of_a_guessed_decimal_precision():
    result=binance_contract_rules({"filters":[]})
    assert result["quantity_step"]=="" and result["quantity_rule_model"]=="unknown"
