"""Exact OKX perpetual facts. Never normalize monetary values from CCXT floats."""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, localcontext
from typing import Any, Mapping

_DECIMAL = re.compile(r"^-?(?:0|[1-9][0-9]{0,35})(?:\.[0-9]{1,36})?$")
_INSTRUMENT = re.compile(r"^([A-Z0-9]{1,20})-(USDT|USD)-SWAP$")


class AccountDataError(ValueError):
    """A bounded error code; raw exchange payloads and credentials stay out of logs."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def decimal(value: Any, *, positive: bool = False, nonnegative: bool = False) -> Decimal:
    if not isinstance(value, str) or _DECIMAL.fullmatch(value) is None:
        raise AccountDataError("INVALID_DECIMAL")
    result = Decimal(value)
    if (positive and result <= 0) or (nonnegative and result < 0):
        raise AccountDataError("INVALID_DECIMAL_SIGN")
    return result


def exact(value: Decimal) -> str:
    if not value.is_finite():
        raise AccountDataError("NONFINITE_AMOUNT")
    return format(value, "f")


def identifier(value: Any) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 128:
        raise AccountDataError("INVALID_ID")
    if any(ord(c) < 32 or ord(c) > 126 for c in value):
        raise AccountDataError("INVALID_ID")
    return value


def timestamp(value: Any) -> int:
    if not isinstance(value, str) or not value.isascii() or not value.isdigit():
        raise AccountDataError("INVALID_EVENT_TIME")
    result = int(value)
    if not 0 <= result < 2**53:
        raise AccountDataError("INVALID_EVENT_TIME")
    return result


def position_side(raw: Mapping[str, Any]) -> str:
    side = raw.get("posSide")
    if side not in {"long", "short"}:
        raise AccountDataError("HEDGE_POSITION_SIDE_REQUIRED")
    return str(side)


@dataclass(frozen=True, slots=True)
class Contract:
    instrument: str
    base: str
    quote: str
    settle: str
    kind: str
    value: Decimal
    value_currency: str
    lot: Decimal

    @classmethod
    def from_okx(cls, raw: Mapping[str, Any]) -> Contract:
        instrument = raw.get("instId")
        match = _INSTRUMENT.fullmatch(instrument) if isinstance(instrument, str) else None
        if raw.get("instType") != "SWAP" or match is None:
            raise AccountDataError("UNSUPPORTED_PRODUCT")
        base, quote = match.groups()
        kind, settle, value_currency = raw.get("ctType"), raw.get("settleCcy"), raw.get("ctValCcy")
        if not ((kind == "linear" and quote == settle == "USDT" and value_currency == base)
                or (kind == "inverse" and quote == value_currency == "USD" and settle == base)):
            raise AccountDataError("UNSUPPORTED_CONTRACT")
        return cls(instrument, base, quote, str(settle), str(kind),
                   decimal(raw.get("ctVal"), positive=True), str(value_currency),
                   decimal(raw.get("lotSz"), positive=True))

    def quantities(self, contracts: Decimal, price: Decimal) -> dict[str, str]:
        if contracts < 0 or price <= 0:
            raise AccountDataError("INVALID_QUANTITY_PRICE")
        with localcontext() as context:
            context.prec = 80
            value = contracts * self.value
            base = value if self.kind == "linear" else value / price
            quote = value * price if self.kind == "linear" else value
            return {"contracts": exact(contracts), "baseQuantity": exact(base), "quoteNotional": exact(quote)}

    def pnl(self, contracts: Decimal, entry: Decimal, exit: Decimal, side: str) -> Decimal:
        if contracts < 0 or entry <= 0 or exit <= 0 or side not in {"long", "short"}:
            raise AccountDataError("INVALID_PNL_INPUT")
        with localcontext() as context:
            context.prec = 80
            result = contracts * self.value * (exit - entry if self.kind == "linear" else 1 / entry - 1 / exit)
            return result if side == "long" else -result

    def wire(self) -> dict[str, str]:
        return {"instrument": self.instrument, "base": self.base, "quote": self.quote,
                "settle": self.settle, "kind": self.kind, "contractValue": exact(self.value),
                "contractValueCurrency": self.value_currency, "lotSize": exact(self.lot)}


def fill(raw: Mapping[str, Any], contract: Contract) -> dict[str, Any]:
    if raw.get("instType") != "SWAP" or raw.get("instId") != contract.instrument:
        raise AccountDataError("FILL_MARKET_MISMATCH")
    # REST billId is authoritative, including liquidation/ADL's negative tradeIds.
    # WS order notifications are persisted as observations and trigger REST repair;
    # their cumulative quantities are never synthesized into fills.
    bill = identifier(raw.get("billId"))
    trade = identifier(raw.get("tradeId"))
    order = None if raw.get("ordId") == "" else identifier(raw.get("ordId"))
    side = raw.get("side")
    if side not in {"buy", "sell"}:
        raise AccountDataError("INVALID_FILL_SIDE")
    leg = position_side(raw)
    price = decimal(raw.get("fillPx"), positive=True)
    quantity = decimal(raw.get("fillSz"), positive=True)
    fee = None if raw.get("fee") in (None, "") else exact(decimal(raw.get("fee")))
    fee_currency = identifier(raw["feeCcy"]) if raw.get("feeCcy") else None
    if fee is not None and not fee_currency:
        raise AccountDataError("FEE_CURRENCY_REQUIRED")
    realized = None if raw.get("fillPnl") in (None, "") else exact(decimal(raw.get("fillPnl")))
    return {"fillId": bill, "tradeId": trade, "orderId": order, "instrument": contract.instrument,
            "positionSide": leg, "side": side,
            "effect": "open" if (leg == "long") == (side == "buy") else "close",
            "eventTimeMs": timestamp(raw.get("fillTime") or raw.get("ts")),
            "exchangeRecordTimeMs": timestamp(raw.get("ts")),
            "price": exact(price), **contract.quantities(quantity, price),
            "settleCurrency": contract.settle, "feeCashChange": fee, "feeCurrency": fee_currency,
            "exchangeRealizedPnl": realized, "contract": contract.wire()}


def _optional(raw: Mapping[str, Any], key: str, **sign: bool) -> Decimal | None:
    return None if raw.get(key) in (None, "") else decimal(raw.get(key), **sign)


def position(raw: Mapping[str, Any], contract: Contract) -> dict[str, Any]:
    if raw.get("instId") != contract.instrument or raw.get("instType") != "SWAP":
        raise AccountDataError("POSITION_MARKET_MISMATCH")
    leg = position_side(raw)
    quantity = decimal(raw.get("pos"), nonnegative=True)
    mark = _optional(raw, "markPx", positive=True)
    avg = _optional(raw, "avgPx", nonnegative=True)
    unrealized = None if raw.get("upl") in (None, "") else exact(decimal(raw.get("upl")))
    mode = raw.get("mgnMode") if raw.get("mgnMode") in {"cross", "isolated"} else None
    leverage = _optional(raw, "lever", positive=True)
    # OKX sends no price when liquidation is out of reach; a non-positive
    # estimate is equally not a price a position can be liquidated at.
    liquidation = _optional(raw, "liqPx")
    # Isolated positions hold their own margin; cross positions report the
    # initial margin they use from the shared balance.
    margin = _optional(raw, "margin" if mode == "isolated" else "imr", nonnegative=True) if mode else None
    margin_currency = identifier(raw["ccy"]) if raw.get("ccy") else contract.settle
    return {"positionId": identifier(raw.get("posId")), "instrument": contract.instrument,
            "positionSide": leg, "contracts": exact(quantity), "marginMode": mode,
            "entryPrice": exact(avg) if avg is not None else None,
            "markPrice": exact(mark) if mark is not None else None,
            "baseQuantity": contract.quantities(quantity, mark)["baseQuantity"] if mark else None,
            "unrealizedPnl": unrealized, "settleCurrency": contract.settle,
            "leverage": exact(leverage) if leverage is not None else None,
            "liquidationPrice": exact(liquidation) if liquidation is not None and liquidation > 0 else None,
            "priceCurrency": contract.quote,
            "margin": exact(margin) if margin is not None else None, "marginCurrency": margin_currency,
            "eventTimeMs": timestamp(raw.get("uTime")), "contract": contract.wire()}


def _cost_rates(raw: Mapping[str, Any], maker: str, taker: str) -> dict[str, str] | None:
    # OKX reports a charge as a negative rate and a rebate as a positive one.
    # Stored as cost rates: positive is a fee, negative a rebate.
    if raw.get(maker) in (None, "") and raw.get(taker) in (None, ""):
        return None
    with localcontext() as context:
        context.prec = 80
        # Subtracting from zero keeps a zero rate "0", never "-0".
        return {"maker": exact(Decimal(0) - decimal(raw.get(maker))), "taker": exact(Decimal(0) - decimal(raw.get(taker)))}


# Funding account (#575 PL-6). Exchange states collapse to five the panel can explain;
# a state OKX adds later reads "unknown" rather than being guessed.
_DEPOSIT_STATES = {"0": "pending", "8": "pending", "1": "completed", "2": "completed",
                   "11": "held", "12": "held", "13": "held", "14": "held"}
_WITHDRAWAL_STATES = {"2": "completed", "-1": "failed", "-2": "canceled",
                      **{state: "pending" for state in ("-3", "0", "1", "3", "4", "5", "6", "7", "8", "9",
                                                         "10", "12", "15", "16", "17")}}
# OKX transfer bills name the accounts on each side: 6 funding, 18 trading.
_TRANSFER_ACCOUNTS = {"6": "funding", "18": "trading"}


def _label(value: Any) -> str:
    if value in (None, ""):
        return ""
    if not isinstance(value, str) or len(value) > 64 or any(ord(c) < 32 or ord(c) > 126 for c in value):
        raise AccountDataError("INVALID_LABEL")
    return value


def funding_balance(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {"currency": identifier(raw.get("ccy")),
            "total": exact(decimal(raw.get("bal"), nonnegative=True)),
            "available": exact(decimal(raw.get("availBal"), nonnegative=True)),
            "frozen": exact(decimal(raw.get("frozenBal"), nonnegative=True))}


def deposit(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Addresses and transaction ids stay in the exchange's records; the panel needs neither."""
    return {"id": identifier(raw.get("depId")), "currency": identifier(raw.get("ccy")), "chain": _label(raw.get("chain")),
            "amount": exact(decimal(raw.get("amt"), nonnegative=True)),
            "state": _DEPOSIT_STATES.get(raw.get("state"), "unknown"), "eventTimeMs": timestamp(raw.get("ts"))}


def withdrawal(raw: Mapping[str, Any]) -> dict[str, Any]:
    currency = identifier(raw.get("ccy"))
    fee = raw.get("fee")
    return {"id": identifier(raw.get("wdId")), "currency": currency, "chain": _label(raw.get("chain")),
            "amount": exact(decimal(raw.get("amt"), nonnegative=True)),
            "fee": None if fee in (None, "") else exact(decimal(fee, nonnegative=True)),
            "feeCurrency": identifier(raw["feeCcy"]) if raw.get("feeCcy") else currency,
            "state": _WITHDRAWAL_STATES.get(raw.get("state"), "unknown"), "eventTimeMs": timestamp(raw.get("ts"))}


def transfer(raw: Mapping[str, Any]) -> dict[str, Any]:
    """A trading-account transfer bill (type 1): which accounts, which way, how much.

    The bill is the trading account's, so ``direction`` is its side: "in" when
    the trading account received the amount. ``from`` and ``to`` are the
    accounts the exchange names.
    """
    if raw.get("type") != "1":
        raise AccountDataError("TRANSFER_RECORD_INVALID")
    change = decimal(raw.get("balChg"))
    return {"id": identifier(raw.get("billId")), "currency": identifier(raw.get("ccy")),
            "amount": exact(abs(change)), "direction": "in" if change >= 0 else "out",
            "from": _TRANSFER_ACCOUNTS.get(raw.get("from"), "other"), "to": _TRANSFER_ACCOUNTS.get(raw.get("to"), "other"),
            "eventTimeMs": timestamp(raw.get("ts"))}


def fee_rates(raw: Mapping[str, Any]) -> dict[str, Any]:
    """The account's standard perpetual fee rates at its current tier.

    These estimate costs only. Fills and bills record the fees actually charged,
    and some contracts carry rates of their own.
    """
    if raw.get("instType") != "SWAP":
        raise AccountDataError("FEE_RATE_SCOPE_INVALID")
    tier = raw.get("level")
    return {"tier": identifier(tier) if tier else None,
            "usdtMargined": _cost_rates(raw, "makerU", "takerU"),
            "coinMargined": _cost_rates(raw, "maker", "taker"),
            "exchangeTimeMs": timestamp(raw.get("ts"))}


def bill(raw: Mapping[str, Any]) -> dict[str, Any]:
    kind = identifier(raw.get("type"))
    currency = identifier(raw.get("ccy"))
    return {"billId": identifier(raw.get("billId")), "type": kind,
            "subType": str(raw.get("subType") or ""), "instrument": str(raw.get("instId") or ""),
            "instrumentType": str(raw.get("instType") or ""),
            "inSelectedScope": raw.get("instType") == "SWAP" and isinstance(raw.get("instId"), str) and _INSTRUMENT.fullmatch(raw["instId"]) is not None,
            "positionSide": raw.get("posSide") if raw.get("posSide") in {"long", "short"} else None,
            "category": "funding" if kind == "8" else "trade" if kind == "2" else "other_adjustment",
            "currency": currency, "cashChange": exact(decimal(raw.get("balChg"))),
            "feeCashChange": None if raw.get("fee") in (None, "") else exact(decimal(raw.get("fee"))),
            "eventTimeMs": timestamp(raw.get("ts"))}


def order(raw: Mapping[str, Any], contract: Contract) -> dict[str, Any]:
    if raw.get("instType") != "SWAP" or raw.get("instId") != contract.instrument:
        raise AccountDataError("ORDER_MARKET_MISMATCH")
    if raw.get("side") not in {"buy", "sell"}:
        raise AccountDataError("INVALID_ORDER_SIDE")
    return {"orderId":identifier(raw.get("ordId")),"instrument":contract.instrument,
            "positionSide":position_side(raw),"side":raw["side"],"state":str(raw.get("state") or "unknown"),
            "contracts":exact(decimal(raw.get("sz"),nonnegative=True)),
            "filledContracts":exact(decimal(raw.get("accFillSz"),nonnegative=True)),
            "price":None if raw.get("px") in (None, "") else exact(decimal(raw.get("px"),nonnegative=True)),
            "eventTimeMs":timestamp(raw.get("uTime")),"createdMs":timestamp(raw.get("cTime")),
            "settleCurrency":contract.settle}
