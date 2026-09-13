"""Qualify and detach small host feedback without a JSON decode round trip."""
from decimal import Decimal

from .qualified_json import encode_ascii_tree


def prepare_feedback(request):
    # Deliberately narrower than the SDK: unusual values retain strict JSONL.
    remaining = [256]
    def clone(value, depth=0):
        remaining[0] -= 1
        if remaining[0] < 0 or depth > 8:
            raise ValueError
        kind = type(value)
        if kind is Decimal:
            # The existing JSON transport uses default=str for financial values.
            return clone(str(value), depth)
        if value is None or kind is bool:
            return value
        if kind is int and abs(value) <= 9007199254740991:
            return value
        if kind is str and len(value) <= 1024 and value.isascii() and "\x7f" not in value:
            return value
        if kind is dict and len(value) <= 32:
            if any(type(key) is not str for key in value):
                raise ValueError
            return {clone(key, depth+1): clone(item, depth+1) for key, item in value.items()}
        if kind is list and len(value) <= 32:
            return [clone(item, depth+1) for item in value]
        raise ValueError
    try:
        detached = clone(request)
    except ValueError:
        return None
    wire = encode_ascii_tree(detached)
    if len(wire) > 32768:
        return None
    return detached, wire
