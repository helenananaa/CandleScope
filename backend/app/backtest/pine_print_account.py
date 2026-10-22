"""Frozen V2 account events over the separate physical print/book clock."""
from copy import deepcopy
from decimal import Decimal

from app.market_dataset.snapshot import MarketEvent
from app.simulation.account_execution import publish_account_liquidation
from app.simulation.linear_perp_account_v2 import LinearPerpetualAccountV2
from app.backtest.errors import BacktestError

CONTRACT = "candlescope.pine-v2-print-account/1"
AUXILIARY = {"INSTRUMENT_RULES", "MARK_INDEX", "FUNDING"}
FIDELITIES = {"TRADE_TAPE", "BOOK_ASSISTED", "BOOK_DEPTH", "BOOK_SAMPLED"}


def events(wire):
    """Account events precede market events on ties; source order stays stable."""
    market = [MarketEvent(**item) for item in wire["execution_events"]]
    contract = wire.get("pine_v2_print_contract")
    if contract is None:
        return market
    if (contract != CONTRACT or wire.get("account_model") != "LINEAR_PERP_ONE_WAY_V2"
            or wire.get("execution_fidelity") not in FIDELITIES):
        raise BacktestError("FIDELITY_UNSUPPORTED", "invalid Pine V2 physical-clock contract")
    if not market or any(row.role not in {"TRADES", "ORDER_BOOK"} for row in market):
        raise BacktestError("DATA_ROLE_MISSING", "V2 print account requires frozen physical observations")
    account = [MarketEvent(index + 1, row["time_ms"], row["role"], deepcopy(row["payload"]))
               for index, row in enumerate(wire["account_events"])]
    if not account or any(row.role not in AUXILIARY for row in account):
        raise BacktestError("DATA_ROLE_MISSING", "V2 print account requires historical account events")
    rows = [(row, 0, index) for index, row in enumerate(account)]
    rows.extend((row, 1, index) for index, row in enumerate(market))
    rows.sort(key=lambda item: (item[0].event_time_ms, item[1], item[2]))
    result = []
    for index, (row, source, _) in enumerate(rows):
        payload = deepcopy(row.payload)
        if source == 1 and row.role == "TRADES":
            if not payload.get("source_sequence"):
                payload["source_sequence"] = row.sequence
        result.append(MarketEvent(index + 1, row.event_time_ms, row.role, payload))
    return result


def observe_market(kernel, event):
    """V2 marks come only from historical MARK_INDEX, never from a trade quote."""
    if isinstance(kernel.account, LinearPerpetualAccountV2):
        kernel.account.validate_ready()
    else:
        kernel.account.mark = Decimal(str(event.payload["price"]))
    if kernel.market_observer is not None:
        kernel.market_observer(event)


def apply_account(kernel, event, *, record_equity=False):
    if not isinstance(kernel.account, LinearPerpetualAccountV2) or event.role not in AUXILIARY:
        raise BacktestError("FIDELITY_MISLABEL", "historical account observation requires V2")
    kernel._last_event = event
    if event.role == "FUNDING" and kernel.market_observer is not None:
        kernel.market_observer(event)
    kernel.account.apply(event)
    publish_account_liquidation(kernel)
    if kernel.market_observer is not None:
        kernel.market_observer(event)
    if record_equity:
        kernel._record_equity_point({"sequence": event.sequence, "event_time_ms": event.event_time_ms,
            "equity": str(kernel.account.equity()), "position_qty": str(kernel.account.position_qty)})


def record_decision(kernel, decision):
    """Keep Host transcripts and the V2 decision chain in the same checkpoint."""
    kernel.decisions.append(decision)
    from app.market_dataset.snapshot import sha256_hex
    from app.simulation.execution_realism import EXECUTION_REALISM_V2
    if kernel.execution_model_revision == EXECUTION_REALISM_V2:
        kernel._decision_chain_hash = "sha256:" + sha256_hex({
            "previous": kernel._decision_chain_hash, "decision": decision})
        kernel._decision_count += 1
        if decision["intents"]:
            kernel.frozen_intents.append({"sequence": decision["sequence"], "intents": deepcopy(decision["intents"])})
