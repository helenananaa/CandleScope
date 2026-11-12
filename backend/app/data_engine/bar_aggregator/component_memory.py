"""Mutable component index with cached immutable accepted-value weights.

No data cache or delivery owner: this is the existing builder/snapshot index.
Foreign mutable entries retain dict aliasing and use diagnostic value traversal.
"""
from copy import deepcopy
import sys

from app.data_engine.memory_budget import RetainedMetadata, retained_size
from app.data_engine.readonly import ReadonlyFields, frozen_reference_weight


class ComponentSnapshots(dict, RetainedMetadata):
    __slots__ = ('_payload_bytes', '_proof_bytes', '_foreign')

    def __init__(self, *args, **kwargs):
        dict.__init__(self)
        self._payload_bytes = self._proof_bytes = 0
        self._foreign = None
        self.update(*args, **kwargs)

    def _track(self, key, value, sign):
        if type(value) is ReadonlyFields:
            self._payload_bytes += sign * (sys.getsizeof(key) + value.estimated_bytes)
            proof = value.get('source_ref')
            if proof:
                self._proof_bytes += sign * (sys.getsizeof(key) + frozen_reference_weight(proof))
        elif sign > 0:
            if self._foreign is None:
                self._foreign = {}
            self._foreign[key] = value
        elif self._foreign is not None:
            self._foreign.pop(key, None)
            if not self._foreign:
                self._foreign = None

    def __setitem__(self, key, value):
        existed = key in self
        old = self[key] if existed else None
        dict.__setitem__(self, key, value)
        if existed:
            self._track(key, old, -1)
        self._track(key, value, 1)

    def __delitem__(self, key):
        old = self[key]
        dict.__delitem__(self, key)
        self._track(key, old, -1)

    def clear(self):
        dict.clear(self)
        self._payload_bytes = self._proof_bytes = 0
        self._foreign = None

    def pop(self, key, *default):
        if len(default) > 1:
            raise TypeError('pop expected at most 2 arguments')
        if key not in self:
            return dict.pop(self, key, *default)
        value = self[key]
        del self[key]
        return value

    def popitem(self):
        key, value = dict.popitem(self)
        self._track(key, value, -1)
        return key, value

    def setdefault(self, key, default=None):
        if key not in self:
            self[key] = default
        return self[key]

    def update(self, *args, **kwargs):
        if len(args) > 1:
            raise TypeError('update expected at most 1 argument')
        if args:
            other = args[0]
            pairs = ((key, other[key]) for key in other.keys()) if hasattr(other, 'keys') else other
            for key, value in pairs:
                self[key] = value
        for key, value in kwargs.items():
            self[key] = value

    def __ior__(self, other):
        self.update(other)
        return self

    def copy(self):
        result = type(self)()
        dict.update(result, self)
        result._payload_bytes = self._payload_bytes
        result._proof_bytes = self._proof_bytes
        result._foreign = self._foreign.copy() if self._foreign is not None else None
        return result

    def __copy__(self):
        return self.copy()

    def __deepcopy__(self, memo):
        result = type(self)()
        memo[id(self)] = result
        for key, value in self.items():
            result[deepcopy(key, memo)] = deepcopy(value, memo)
        return result

    def __reduce_ex__(self, protocol):
        # Initialize counters before pickle populates dictionary items.
        return (type(self), (), None, None, iter(self.items()))

    def publication_copy(self, memo):
        if self._foreign is None:
            return self.copy()
        return type(self)((key, value if type(value) is ReadonlyFields else deepcopy(value, memo))
                          for key, value in self.items())

    @property
    def foreign_entries(self):
        return len(self._foreign) if self._foreign is not None else 0

    @property
    def source_proof_bytes(self):
        return self._proof_bytes

    @property
    def estimated_bytes(self):
        foreign = (sum(retained_size([key, value])[0] for key, value in self._foreign.items())
                   if self._foreign is not None else 0)
        return (sys.getsizeof(self) + self._payload_bytes + foreign
                + sys.getsizeof(self._payload_bytes) + sys.getsizeof(self._proof_bytes)
                + (sys.getsizeof(self._foreign) if self._foreign is not None else 0))

    def _memory_metadata(self):
        return (self._payload_bytes, self._proof_bytes, self._foreign)
