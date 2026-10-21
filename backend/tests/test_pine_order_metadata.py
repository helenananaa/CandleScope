"""Host annotation admission, actual-fill binding and leg selection contracts."""
import pytest

from app.backtest.errors import BacktestError
from app.backtest.pine_order_metadata import CONTRACT, declaration, fill_annotation


@pytest.mark.parametrize("action", ["entry", "order", "close", "close_all", "exit"])
def test_metadata_is_negotiated_and_defensively_copied(action):
    value={"comment":"备注", "alert_message":"{{strategy.order.id}}", "disable_alert":False}
    intent={"action":action,"metadata":value}
    with pytest.raises(BacktestError) as error:
        declaration(intent)
    assert error.value.code=="EXTERNAL_UNSUPPORTED"
    result=declaration(intent,CONTRACT)
    value["comment"]="changed"
    assert result["comment"]=="备注"


@pytest.mark.parametrize("value", [None,[],{}, {"disable_alert":1}, {"disable_alert":"true"},
    {"disable_alert":False,"comment":None}, {"disable_alert":False,"comment":1},
    {"disable_alert":False,"unknown":"value"}])
def test_malformed_metadata_is_rejected(value):
    with pytest.raises(BacktestError) as error:
        declaration({"action":"entry","metadata":value},CONTRACT)
    assert error.value.code=="EXTERNAL_PROTOCOL_ERROR"


def test_exit_specific_keys_are_not_valid_for_an_entry_or_cancel():
    value={"comment_loss":"loss","disable_alert":False}
    assert declaration({"action":"exit","metadata":value},CONTRACT)==value
    for action in ("entry","cancel"):
        with pytest.raises(BacktestError):
            declaration({"action":action,"metadata":value},CONTRACT)


@pytest.mark.parametrize("role",["profit","loss","trailing"])
@pytest.mark.parametrize("specific", [False,True])
def test_actual_fill_leg_selects_specific_values_and_preserves_empty_override(role,specific):
    value={"comment":"generic", "alert_message":"message", "disable_alert":False}
    if specific:
        value.update({f"comment_{role}":"", f"alert_{role}":""})
    annotation=fill_annotation(value,role)["pine_metadata"]
    assert annotation["comment"]==("" if specific else "generic")
    assert annotation["alert_message"]==("" if specific else "message")
    assert annotation["fill_role"]==role
    assert annotation["alert_enabled"] is True


def test_disabling_alert_does_not_drop_order_comment_or_expand_templates():
    value={"comment":"keep", "alert_message":"{{strategy.order.id}}", "disable_alert":True}
    assert fill_annotation(value,"entry")["pine_metadata"]=={
        "contract":CONTRACT,"fill_role":"entry","comment":"keep",
        "alert_message":"{{strategy.order.id}}","alert_enabled":False}


def test_missing_metadata_does_not_change_existing_fill_wire():
    assert declaration({"action":"entry"}) is None
    assert fill_annotation(None,"entry")=={}


def test_annotation_report_is_bound_to_actual_fill_and_never_reorders_account_records():
    from app.backtest.pine_order_metadata import enrich_fills
    fill={"order_id":"ord-1","sequence":3,"qty":"2","fee":"0.1"}
    allocation={"order_id":"ord-1","sequence":3,"annotation":fill_annotation({"comment":"keep","disable_alert":True},"entry")}
    result=enrich_fills([fill],[allocation])
    assert result[0]["qty"]=="2" and result[0]["fee"]=="0.1"
    assert result[0]["pine_comment"]=="keep" and result[0]["pine_alert_enabled"] is False
    assert "pine_comment" not in fill
    with pytest.raises(BacktestError,match="allocation differs"):
        enrich_fills([fill],[{**allocation,"sequence":4}])


def test_negotiated_metadata_cannot_be_silently_removed_from_an_active_order_stream():
    from app.backtest.external_orders import ExternalOrders
    from app.simulation.kernel import SimulationKernel
    orders=ExternalOrders(SimulationKernel())
    orders.negotiate_metadata(CONTRACT)
    with pytest.raises(BacktestError,match="contract changed"):
        orders.negotiate_metadata(None)

