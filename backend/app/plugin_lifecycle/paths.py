"""Reject filesystem indirection, including Windows junction/reparse points."""

import stat
from pathlib import Path


def is_link(path: Path) -> bool:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0)
        & 0x400  # FILE_ATTRIBUTE_REPARSE_POINT
    )
