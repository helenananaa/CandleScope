import pytest
from pydantic import ValidationError
from app.api.v1.data_preparation import AutomaticHostExecution
from app.backtest.native_contracts import ExternalRunRequest


def account():
    return dict(account_model="LINEAR_PERP_ONE_WAY_V2",account_data={"symbol":"BTCUSDT","events":[
        dict(time_ms=-1,role="MARK_INDEX",payload={"mark_price":"10"})]})


def request(**extra):
    return dict(dataset_id="data",data_epoch="epoch000",snapshot_hash="hash0000",start_time_ms=0,end_time_ms=600000,
        interval="1m",language="pine",source='strategy("admission")',context={"symbol":"BINANCE:BTCUSDT","timeframe":"1"},
        **account(),**extra)


@pytest.mark.parametrize("callbacks",[False,True])
def test_automatic_trade_account_does_not_require_bar_fill_callbacks(callbacks):
    value=AutomaticHostExecution.model_validate(dict(**account(),execution_fidelity="TRADE_TAPE",fill_recalculation=callbacks))
    assert value.account_model=="LINEAR_PERP_ONE_WAY_V2" and value.fill_recalculation is callbacks


@pytest.mark.parametrize("mode",["TRADE_TAPE","BOOK_ASSISTED","BOOK_DEPTH","BOOK_SAMPLED"])
def test_direct_physical_account_profile_accepts_before_any_market_acquisition(mode):
    assert ExternalRunRequest.model_validate(request(execution_fidelity=mode)).execution_fidelity==mode


@pytest.mark.parametrize("changes,pattern",[
    ({"execution_fidelity":"TRADE_TAPE","bar_path_scenario":"OHLC_NEAREST_EXTREME_PATH_V2","execution_model_revision":"EXECUTION_REALISM_V2","participation_rate":.2},"synthetic BAR"),
    ({"execution_fidelity":"BOOK_DEPTH","execution_model_revision":"EXECUTION_REALISM_V2","participation_rate":.2},"book capacity"),
    ({"execution_fidelity":"BOOK_ASSISTED","language":"pyne"},"Input should be .pine."),
])
def test_invalid_physical_combination_rejects_at_schema_boundary(changes,pattern):
    with pytest.raises(ValidationError,match=pattern):
        ExternalRunRequest.model_validate({**request(),**changes})
