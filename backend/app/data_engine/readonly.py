"""Immutable field maps for safely sharing published component values.

This is an ownership primitive, not an aggregation/coverage contract. Nested
maps and sequences are frozen as well; no caller-owned container is retained.
"""
from collections.abc import Mapping
from decimal import Decimal
from fractions import Fraction
from numbers import Number
from types import MappingProxyType

_SCALARS = (str, bytes, Number, bool, type(None), Decimal, Fraction)


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
    if isinstance(value, ReadonlyFields) or isinstance(value, _SCALARS):
        return value
    if isinstance(value, Mapping):
        result = object.__new__(ReadonlyFields)
        object.__setattr__(result, '_values', MappingProxyType(_mapping(value, active)))
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


class ReadonlyFields(Mapping):
    __slots__ = ('_values',)

    def __init__(self, values):
        mapping = values if isinstance(values, Mapping) else dict(values)
        object.__setattr__(self, '_values', MappingProxyType(_mapping(mapping, set())))

    def __setattr__(self, name, value):
        raise TypeError('published fields are read-only')

    def __getitem__(self, key):
        return self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def __deepcopy__(self, memo):
        return self
