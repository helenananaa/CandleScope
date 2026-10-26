"""Bound disposable catalog generations without touching frozen market bodies.

Call detach under the metadata reader/publisher lock. Removal happens outside
that lock: readers already hold parsed payloads, and new readers use the index.
An interrupted removal is resumed by the next background maintenance pass.
"""

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


def _generation(name):
    return len(name) == 32 and all(c in "0123456789abcdef" for c in name)


def detach_obsolete_generations(root: Path, paths, *, active=()):
    generations = root / "generations"
    retired = root / "_retired_generations"
    if generations.is_symlink() or retired.is_symlink() or not generations.is_dir():
        return
    if any(not (root / path).is_file() for path in paths):
        # An incomplete current publication must not trigger retirement.
        return
    keep = set(active)
    for path in paths:
        parts = path.split("/")
        if len(parts) > 2 and parts[0] == "generations":
            keep.add(parts[1])
    candidates = [
        p
        for p in generations.iterdir()
        if _generation(p.name)
        and not p.is_symlink()
        and p.is_dir()
        and p.name not in keep
    ]
    # Keep one prior generation for diagnosis/recovery, plus all
    # generations named by the current index and any active staging writer.
    candidates.sort(key=lambda p: p.stat().st_mtime_ns, reverse=True)
    if len(candidates) <= 1:
        return
    retired.mkdir(exist_ok=True)
    for path in candidates[1:]:
        path.rename(retired / path.name)


def remove_retired_generations(root: Path):
    retired = root / "_retired_generations"
    if retired.is_symlink() or not retired.is_dir():
        return
    for path in retired.iterdir():
        if _generation(path.name) and not path.is_symlink() and path.is_dir():
            try:
                shutil.rmtree(path)
            except FileNotFoundError:
                pass
            except OSError:
                logger.warning(
                    "Could not reclaim obsolete catalog generation %s",
                    path.name,
                    exc_info=True,
                )
