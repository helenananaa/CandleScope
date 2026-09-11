"""Read-only internal JSON trees for sharing unchanged snapshot components.

Public broker snapshots are decoded into ordinary, detached containers. Internal
actor/storage projections may share these values; wire JSON is unchanged.
"""


def _readonly(*args, **kwargs):
    raise TypeError("replay snapshot component is read-only")


class FrozenDict(dict):
    __slots__ = ("_sealed",)
    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _readonly

    __setattr__ = __delattr__ = _readonly

    def __init__(self, value):
        if getattr(self, "_sealed", False):
            _readonly()
        if any(type(key) is not str for key in value):
            raise TypeError("snapshot JSON keys must be strings")
        dict.__init__(self, ((key, freeze(item)) for key, item in value.items()))
        object.__setattr__(self, "_sealed", True)

    def __deepcopy__(self, memo):
        return self


class FrozenList(list):
    __slots__ = ("_sealed",)
    __setitem__ = __delitem__ = append = clear = extend = insert = pop = remove = reverse = sort = __iadd__ = __imul__ = _readonly

    __setattr__ = __delattr__ = _readonly

    def __init__(self, value):
        if getattr(self, "_sealed", False):
            _readonly()
        list.__init__(self, (freeze(item) for item in value))
        object.__setattr__(self, "_sealed", True)

    def __deepcopy__(self, memo):
        return self


def freeze(value):
    if type(value) in (FrozenDict, FrozenList):
        return value
    if type(value) is dict:
        return FrozenDict(value)
    if type(value) in (list, tuple):
        return FrozenList(value)
    if value is None or type(value) in (str, int, bool):
        return value
    raise TypeError("internal snapshot contains a non-JSON primitive")
