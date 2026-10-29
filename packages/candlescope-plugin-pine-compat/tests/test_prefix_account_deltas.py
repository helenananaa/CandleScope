"""V2 account compression preserves values, clears and legacy full frames."""
from copy import deepcopy
import pytest
from candlescope_plugin_pine_compat.prefix_transport import PrefixInput, CONTRACT


def seed(contract=CONTRACT):
    return dict(identity=dict(prefix_append=contract),bars=[dict(time=0)],
        accounts=[dict(time=0,position_size=1,position_avg_price=10,equity=1000,
                       initial_capital=1000,netprofit=0,openprofit=0)])


def test_deltas_reconstruct_multiple_accounts_and_explicitly_clear_an_average_price():
    prefix=PrefixInput(); initial=seed(); prefix.decode(initial)
    actual=prefix.decode(dict(operation="append_prefix",prefix_base=1,bars=[dict(time=60),dict(time=120)],
        account_deltas=[dict(time=60,position_size=0,position_avg_price=None),dict(time=120,equity=1002,netprofit=2)]))
    expected=[initial["accounts"][0],{**initial["accounts"][0],"time":60,"position_size":0,"position_avg_price":None}]
    expected.append({**expected[-1],"time":120,"equity":1002,"netprofit":2})
    assert actual["accounts"]==expected
    full={**expected[-1],"time":180,"position_size":2,"position_avg_price":15}
    assert prefix.decode(dict(operation="append_prefix",prefix_base=3,bars=[dict(time=180)],accounts=[full]))["accounts"][-1]==full
    assert initial==seed()


@pytest.mark.parametrize("damage",["legacy","both","unknown","count","not_list","not_object"])
def test_invalid_deltas_are_rejected_before_mutating_the_bound_prefix(damage):
    prefix=PrefixInput(); prefix.decode(seed("candlescope.pine-prefix/1" if damage=="legacy" else CONTRACT))
    before=deepcopy(prefix.request)
    request=dict(operation="append_prefix",prefix_base=1,bars=[dict(time=60)],account_deltas=[dict(time=60)])
    if damage=="both": request["accounts"]=[seed()["accounts"][0]]
    if damage=="unknown": request["account_deltas"][0]["unknown"]=1
    if damage=="count": request["account_deltas"]=[]
    if damage=="not_list": request["account_deltas"]={}
    if damage=="not_object": request["account_deltas"]=[None]
    with pytest.raises(ValueError): prefix.decode(request)
    assert prefix.request==before
