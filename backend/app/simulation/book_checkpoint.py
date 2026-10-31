"""JSON checkpoint codecs for visible depth and assumed queue state."""
from decimal import Decimal, InvalidOperation
from app.market_dataset.snapshot import MarketDatasetError


def corrupt(message):
    raise MarketDatasetError(message,code="CHECKPOINT_CORRUPT")


def number(value,*,positive=False):
    try:
        result=Decimal(str(value))
    except (InvalidOperation,ValueError):
        corrupt("invalid book checkpoint number")
    if not result.is_finite() or result<0 or (positive and result==0):
        corrupt("invalid book checkpoint number")
    return result


def encode_book(book):
    return {side:[[str(price),str(qty)] for price,qty in sorted(book[side].items())] for side in ("BUY","SELL")}


def decode_book(value):
    if not isinstance(value,dict) or set(value)!={"BUY","SELL"}:
        corrupt("invalid checkpoint book sides")
    result={}
    for side,rows in value.items():
        if not isinstance(rows,list):
            corrupt("invalid checkpoint book levels")
        levels={}
        for row in rows:
            if not isinstance(row,list) or len(row)!=2:
                corrupt("invalid checkpoint book level")
            price,qty=number(row[0],positive=True),number(row[1])
            if price in levels:
                corrupt("duplicate checkpoint book level")
            levels[price]=qty
        result[side]=levels
    return result
