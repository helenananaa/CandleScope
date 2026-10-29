"""Small immutable field maps for sharing published component values.

This is an ownership primitive, not an aggregation/coverage contract. Values
must already be immutable scalars, tuples or frozensets at construction.
"""
from collections.abc import Mapping
from types import MappingProxyType


class ReadonlyFields(Mapping):
    __slots__ = ("_values",)

    def __init__(self, values):
        object.__setattr__(self, "_values", MappingProxyType(dict(values)))

    def __setattr__(self, name, value):
        raise TypeError("published fields are read-only")

    def __getitem__(self, key):
        return self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def __deepcopy__(self, memo):
        return self
