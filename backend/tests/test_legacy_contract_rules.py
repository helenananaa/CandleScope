from decimal import Decimal as D

import pytest

from app.market_dataset.snapshot import MarketDatasetError, MarketEvent
from app.simulation.contract_accounting import ContractAccount
from app.simulation.kernel import SimulationKernel
from app.backtest.pine_contract_metadata import configure_legacy_account


def test_v1_account_rules_fees_and_restore_preserve_contract_value():
    account = ContractAccount(liquidation_enabled=False, taker_fee_bps=D(10))
    account.apply(MarketEvent(1, 0, 'INSTRUMENT_RULES', dict(multiplier='50', step='.25', tick='.1', min_quantity='2', max_quantity='10')))
    account.mark = D(10)
    account.apply_fill(side='BUY', price=D(10), qty=D(2))
    assert account.fees_paid == 1
    saved = account.snapshot()
    restored = ContractAccount(liquidation_enabled=False, taker_fee_bps=D(10))
    restored.restore(saved)
    assert restored.snapshot() == saved
    assert (restored.multiplier, restored.step, restored.min_quantity, restored.max_quantity) == (50, D('.25'), 2, 10)
    restored.apply_fill(side='SELL', price=D(20), qty=D(2))
    assert restored.quote_balance == D(10997)
    restored.restore({key: value for key, value in saved.items() if key != 'contract_rules'})
    assert restored.multiplier == 1 and restored.step is None and restored.min_quantity is None


@pytest.mark.parametrize('rules',[dict(multiplier='NaN'),dict(step='0'),dict(min_quantity='20', max_quantity='10')])
def test_v1_invalid_rule_updates_do_not_mutate_active_rules(rules):
    account = ContractAccount()
    before = account.snapshot()
    with pytest.raises(MarketDatasetError):
        account.apply(MarketEvent(1,0,'INSTRUMENT_RULES',rules))
    assert account.snapshot() == before


def test_v1_host_fee_uses_frozen_contract_and_quantity_rules():
    kernel = SimulationKernel()
    configure_legacy_account(kernel, dict(account_model='LINEAR_PERP_ONE_WAY_V1',
        context={'metadata': dict(pointValue=50, quantityStep='.25', minContract='2')}))
    assert kernel._execution_fee(D(10),D(2),D(10)) == 1
    assert kernel.account.step == D('.25') and kernel.account.min_quantity == 2
