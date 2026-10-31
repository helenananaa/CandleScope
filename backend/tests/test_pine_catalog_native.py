import json
from decimal import Decimal

import pytest

from tests.test_native_backtests import runtime as runtime, terminal, pytestmark as pytestmark


SOURCE = '''//@version=6
strategy("Catalog unit",initial_capital=10000)
if bar_index==0
    strategy.entry("L",strategy.long,qty=2.49)
if bar_index==2
    strategy.close_all()
plot(syminfo.pointvalue)
plot(syminfo.mincontract)
'''


def catalog(multiplier):
    return dict(priceTickSize="0.1",quoteAsset="USD",contractMultiplier=multiplier,contractValueModel="linear",
                quantityStep=".25",minQuantity="2",quantityOrigin="0",quantityRuleModel="fixed_step")


@pytest.mark.parametrize("multiplier",["50",".01"])
def test_native_catalog_reaches_installed_worker_and_actual_money_report(runtime,monkeypatch,multiplier):
    from app.exchanges import symbol_catalog
    monkeypatch.setattr(symbol_catalog,"get_cached_symbol_metadata",lambda *args:catalog(multiplier))
    host,main=runtime
    record=host.native.create({**main,"source":SOURCE},"catalog-native")
    result=terminal(host.native,record["run_id"])
    assert result["state"]=="COMPLETED",result.get("error")
    result=result["result"]
    assert result["equity"][-1]["value"]==pytest.approx(float(Decimal(10000)+Decimal("2.25")*10*Decimal(multiplier)))
    assert [series["values"][0] for series in result["raw_output"]["plots"]]==[float(multiplier),2]
    wire=json.loads(host.native.db.execute("SELECT wire FROM native_inputs WHERE id=?",(record["run_id"],)).fetchone()[0])
    assert wire["context"]["metadata"]==dict(priceTickSize="0.1",currency="USD",pointValue=float(multiplier),quantityStep=".25",minContract="2")
    assert wire["context"]["contract_profile"]==dict(model="linear",quantityModel="fixed_step")


@pytest.mark.parametrize("change",[dict(contractValueModel="inverse"),dict(quantityRuleModel="significant_digits"),dict(quantityOrigin=".3")])
def test_native_catalog_does_not_enter_an_incompatible_broker_model(runtime,monkeypatch,change):
    from app.exchanges import symbol_catalog
    monkeypatch.setattr(symbol_catalog,"get_cached_symbol_metadata",lambda *args:{**catalog("50"),**change})
    host,main=runtime
    record=host.native.create({**main,"source":SOURCE},"unsupported-catalog")
    result=terminal(host.native,record["run_id"])
    assert result["state"]=="FAILED" and result["result"] is None
    assert "PINE_HOST_METADATA_UNSUPPORTED" in json.dumps(result["error"])
