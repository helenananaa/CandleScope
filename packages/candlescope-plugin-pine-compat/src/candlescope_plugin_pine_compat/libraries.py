"""Explicit, versioned Pine source dependencies supplied by the host."""

import re
from collections.abc import Mapping

LIBRARY_PARAMETER = "__pineLibraries"


def library_sources(options):
    value = options.get("pineLibrarySources", {})
    if not isinstance(value, Mapping) or len(value) > 64:
        raise ValueError("PINE_HOST_LIBRARIES_INVALID: expected at most 64 versioned sources")
    result = {}
    total = 0
    for key, source in value.items():
        if not isinstance(key, str) or not re.fullmatch(
            r"[A-Za-z_][\w.-]*/[A-Za-z_][\w.-]*/[1-9][0-9]*", key
        ):
            raise ValueError("PINE_HOST_LIBRARIES_INVALID: use owner/name/version import paths")
        if not isinstance(source, str) or not source.strip():
            raise ValueError("PINE_HOST_LIBRARIES_INVALID: each library requires source text")
        total += len(source.encode("utf-8"))
        if total > 2_000_000:
            raise ValueError("PINE_HOST_LIBRARIES_INVALID: library sources exceed 2 MB")
        result[key] = source
    return tuple(sorted(result.items()))


def library_digests(options):
    import hashlib

    return {
        key: hashlib.sha256(source.encode("utf-8")).hexdigest()
        for key, source in library_sources(options)
    }
