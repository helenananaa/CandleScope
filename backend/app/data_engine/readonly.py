"""Immutable field maps for safely sharing published component values.

This is an ownership primitive, not an aggregation/coverage contract. Nested
maps and sequences are frozen as well; no caller-owned container is retained.
"""
from collections.abc import Mapping
from decimal import Decimal
from fractions import Fraction
from numbers import Number, Integral, Real, Complex
from types import MappingProxyType
import sys

from app.data_engine.memory_budget import RetainedMetadata

_SCALARS = (str, bytes, int, float, complex, bool, type(None), Decimal, Fraction)


def _mapping(values, active):
    marker = id(values)
    if marker in active:
        raise ValueError('cyclic published fields are unsupported')
    active.add(marker)
    try:
        return {_freeze(key, active): _freeze(value, active) for key, value in values.items()}
    finally:
        active.remove(marker)


def _freeze(value, active):
    if type(value) is ReadonlyFields or type(value) in _SCALARS:
        return value
    # Keep the precision of immutable NumPy scalar values. Mutable arrays are
    # not Numbers and do not enter this path. Other numeric/string subclasses
    # are captured as base values, so caller-owned attributes cannot change
    # an accepted field's subsequent comparison/conversion behavior.
    if type(value).__module__ == "numpy" and isinstance(value, Number):
        return value
    if isinstance(value, str):
        return str.__str__(value)
    if isinstance(value, bytes):
        return bytes(value)
    if isinstance(value, Decimal):
        return Decimal(value)
    if isinstance(value, Fraction):
        return Fraction(value)
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, Real):
        return float(value)
    if isinstance(value, Complex):
        return complex(value)
    if isinstance(value, Mapping):
        result = object.__new__(ReadonlyFields)
        _initialize(result, _mapping(value, active))
        return result
    if isinstance(value, (list, tuple, set, frozenset)):
        marker = id(value)
        if marker in active:
            raise ValueError('cyclic published fields are unsupported')
        active.add(marker)
        try:
            values = (_freeze(item, active) for item in value)
            return frozenset(values) if isinstance(value, (set, frozenset)) else tuple(values)
        finally:
            active.remove(marker)
    raise TypeError(f'unsupported mutable published field type: {type(value).__name__}')


def frozen_reference_weight(value):
    """Conservative Python value bytes per reference, without graph dedup."""
    if type(value) is ReadonlyFields:
        return value.estimated_bytes
    if not (type(value) in _SCALARS or isinstance(value, (tuple, frozenset))
            or (type(value).__module__ == "numpy" and isinstance(value, Number))):
        raise TypeError('reference weights require accepted frozen values')
    weight = sys.getsizeof(value)
    if isinstance(value, (tuple, frozenset)):
        weight += sum(frozen_reference_weight(item) for item in value)
    return weight


def _initialize(result, values):
    proxy = MappingProxyType(values)
    object.__setattr__(result, '_values', proxy)
    # Nested immutable maps already have their weight. Tuples/frozensets are
    # visited only up to those cached map boundaries; no global object cache.
    base = (sys.getsizeof(result) + sys.getsizeof(proxy) + sys.getsizeof(values)
            + sum(frozen_reference_weight(key) + frozen_reference_weight(value)
                  for key, value in values.items()))
    weight = base + sys.getsizeof(base)
    weight = base + sys.getsizeof(weight)  # include the retained counter itself
    object.__setattr__(result, '_estimated_bytes', weight)


class ReadonlyFields(Mapping, RetainedMetadata):
    __slots__ = ('_values', '_estimated_bytes')

    def __init__(self, values):
        mapping = values if isinstance(values, Mapping) else dict(values)
        _initialize(self, _mapping(mapping, set()))

    @property
    def estimated_bytes(self):
        """Cached accepted value weight; sharing may overcount, not an RSS cap."""
        return self._estimated_bytes

    def __setattr__(self, name, value):
        raise TypeError('published fields are read-only')

    def __getitem__(self, key):
        return self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def _memory_metadata(self):
        return (self._estimated_bytes,)

    def __deepcopy__(self, memo):
        # Subclasses may override reads with mutable state; capture their
        # current fields rather than sharing that foreign execution object.
        return self if type(self) is ReadonlyFields else ReadonlyFields(self)
