from decimal import Decimal, localcontext
import pytest
from app.readonly_accounts.normalization import AccountDataError, Contract, bill, decimal, fill, position


def market(inverse=False):
    return {"instType":"SWAP", "instId":"BTC-USD-SWAP" if inverse else "BTC-USDT-SWAP",
            "ctType":"inverse" if inverse else "linear", "settleCcy":"BTC" if inverse else "USDT",
            "ctValCcy":"USD" if inverse else "BTC", "ctVal":"100" if inverse else "0.01", "lotSz":"1"}


def fact(inverse=False, **overrides):
    return {"instType":"SWAP", "instId":market(inverse)["instId"], "billId":"31", "tradeId":"17", "ordId":"29",
            "posSide":"long", "side":"buy", "fillPx":"20000", "fillSz":"3", "fee":"-0.1",
            "feeCcy":"BTC" if inverse else "USDT", "ts":"1709251200123", **overrides}


@pytest.mark.parametrize("inverse,base,quote", [(False,"0.03","600.00"),(True,"0.015","300")])
def test_both_contract_units_and_currency_specific_profit(inverse,base,quote):
    contract=Contract.from_okx(market(inverse)); row=fill(fact(inverse),contract)
    assert Decimal(row['baseQuantity'])==Decimal(base)
    assert Decimal(row['quoteNotional'])==Decimal(quote)
    actual=contract.pnl(Decimal(3),Decimal(20000),Decimal(22000),'long')
    with localcontext() as context:
        context.prec=80
        expected=Decimal(3)/Decimal(2200) if inverse else Decimal(60)
        assert abs(actual-expected) < Decimal('1e-70')
        assert contract.pnl(Decimal(3),Decimal(20000),Decimal(22000),'short')==-actual
    assert row['settleCurrency']==('BTC' if inverse else 'USDT')
    assert row['feeCashChange']=='-0.1'


@pytest.mark.parametrize("leg,side,effect", [('long','buy','open'),('long','sell','close'),('short','sell','open'),('short','buy','close')])
def test_hedge_legs_never_infer_position_direction_from_buy_sell(leg,side,effect):
    row=fill(fact(posSide=leg,side=side),Contract.from_okx(market()))
    assert (row['positionSide'],row['effect'])==(leg,effect)


def test_fee_rebate_missing_fee_and_liquidation_id_preserve_distinct_meanings():
    contract=Contract.from_okx(market())
    assert fill(fact(fee='0.0000000000000000001'),contract)['feeCashChange']=='0.0000000000000000001'
    assert fill(fact(fee='',feeCcy=''),contract)['feeCashChange'] is None
    first=fill(fact(tradeId='-1',billId='32'),contract)
    second=fill(fact(tradeId='-1',billId='33'),contract)
    assert first['fillId'] != second['fillId']
    with pytest.raises(AccountDataError):fill(fact(feeCcy=''),contract)


@pytest.mark.parametrize('value',[0.1,1,True,'NaN','Infinity','1e-8','-Infinity','1.2e2',''])
def test_financial_values_require_exact_exchange_decimal_strings(value):
    with pytest.raises(AccountDataError):decimal(value)


def test_net_mode_usdc_and_delivery_contracts_rejected_without_changing_account_mode():
    with pytest.raises(AccountDataError,match='HEDGE'):fill(fact(posSide='net'),Contract.from_okx(market()))
    for overrides in [{'instType':'FUTURES'},{'instId':'BTC-USDC-SWAP','settleCcy':'USDC'}, {'ctType':'inverse'}]:
        with pytest.raises(AccountDataError):Contract.from_okx({**market(),**overrides})


def test_positions_keep_two_positive_hedge_quantities_and_missing_marks_unknown():
    contract=Contract.from_okx(market(True))
    raw={'instType':'SWAP','instId':contract.instrument,'posId':'4','posSide':'short','pos':'2','markPx':'','avgPx':'20000','upl':'-0.001','uTime':'1709251200000','mgnMode':'cross'}
    row=position(raw,contract)
    assert row['contracts']=='2' and row['positionSide']=='short'
    assert row['baseQuantity'] is None and row['markPrice'] is None
    assert row['unrealizedPnl']=='-0.001'


def test_positions_carry_leverage_liquidation_and_margin_with_their_units():
    linear=Contract.from_okx(market())
    raw={'instType':'SWAP','instId':linear.instrument,'posId':'5','posSide':'long','pos':'12','markPx':'92010.1','avgPx':'91234.5',
         'upl':'93.072','uTime':'1709251200000','mgnMode':'cross','lever':'10','liqPx':'83512.7','imr':'110.412','margin':'','ccy':'USDT'}
    row=position(raw,linear)
    assert (row['marginMode'],row['leverage'],row['liquidationPrice'],row['priceCurrency'])==('cross','10','83512.7','USDT')
    # Cross positions report the initial margin they use from the shared balance.
    assert (row['margin'],row['marginCurrency'],row['settleCurrency'],row['eventTimeMs'])==('110.412','USDT','USDT',1709251200000)
    inverse=Contract.from_okx(market(True))
    isolated=position({**raw,'instId':inverse.instrument,'mgnMode':'isolated','margin':'0.01937','imr':'','ccy':'BTC','liqPx':'103702.95'},inverse)
    assert (isolated['margin'],isolated['marginCurrency'],isolated['priceCurrency'],isolated['settleCurrency'])==('0.01937','BTC','USD','BTC')


@pytest.mark.parametrize("liquidation", ["", "0", "-12.5"])
def test_positions_without_a_reachable_liquidation_price_report_none(liquidation):
    contract=Contract.from_okx(market())
    raw={'instType':'SWAP','instId':contract.instrument,'posId':'6','posSide':'long','pos':'1','avgPx':'20000','uTime':'1709251200000',
         'mgnMode':'cross','lever':'3','liqPx':liquidation,'imr':''}
    row=position(raw,contract)
    assert row['liquidationPrice'] is None and row['margin'] is None and row['marginCurrency']=='USDT'


def test_position_margin_fields_stay_unknown_or_rejected_never_guessed():
    contract=Contract.from_okx(market())
    raw={'instType':'SWAP','instId':contract.instrument,'posId':'7','posSide':'short','pos':'1','avgPx':'20000','uTime':'1709251200000'}
    row=position({**raw,'mgnMode':'unknown','margin':'5','imr':'5'},contract)
    assert (row['marginMode'],row['margin'],row['leverage'])==(None,None,None)
    for bad in [{'lever':'0'},{'lever':'1e3'},{'liqPx':'NaN'},{'mgnMode':'isolated','margin':'-1'}]:
        with pytest.raises(AccountDataError):
            position({**raw,'mgnMode':'cross',**bad},contract)


def test_funding_and_transfers_are_not_trade_pnl_and_do_not_invent_leg_attribution():
    raw={'billId':'42','type':'8','ccy':'BTC','balChg':'-0.00001','fee':'','ts':'1709251200000','instId':'BTC-USD-SWAP'}
    assert bill(raw)['category']=='funding' and bill(raw)['positionSide'] is None
    assert bill({**raw,'type':'1'})['category']=='other_adjustment'
    assert bill(raw)['cashChange']=='-0.00001'


def test_fee_rates_are_cost_rates_per_settlement_with_tier_and_time():
    from app.readonly_accounts.normalization import fee_rates
    raw={'instType':'SWAP','level':'Lv1','maker':'-0.0002','taker':'-0.0005','makerU':'0.00005','takerU':'-0.0005',
         'makerUSDC':'-0.0002','takerUSDC':'-0.0005','ts':'1709251200000'}
    # OKX reports charges as negative rates; stored as costs, a rebate is negative.
    assert fee_rates(raw)=={'tier':'Lv1','usdtMargined':{'maker':'-0.00005','taker':'0.0005'},
                            'coinMargined':{'maker':'0.0002','taker':'0.0005'},'exchangeTimeMs':1709251200000}
    assert fee_rates({**raw,'maker':'0','taker':'0','makerU':'','takerU':''})=={'tier':'Lv1','usdtMargined':None,
                            'coinMargined':{'maker':'0','taker':'0'},'exchangeTimeMs':1709251200000}
    for bad in [{'instType':'SPOT'},{'taker':''},{'makerU':'1e-4'},{'ts':''}]:
        with pytest.raises(AccountDataError):
            fee_rates({**raw,**bad})
