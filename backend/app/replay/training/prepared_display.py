"""Read the base-history policy from an immutable session reference."""

from collections.abc import Mapping

from app.replay.progressive_history import MANIFEST_SCHEMA
from app.replay.sources.bar_source import (
    BAR_TERMINAL_REQUESTED_HORIZON,
    PAGED_BAR_MANIFEST_SCHEMA_VERSION,
)


def uses_prepared_base_history(reference: object) -> bool:
    """Added markets inherit the prepared run's chart-source policy.

    This reads only the replay-owned reference, never the mutable live catalog.
    Legacy catalog runs still require their independently pinned native grids.
    """
    if not isinstance(reference, Mapping):
        return False
    if reference.get("schema_version") != "replay-paged-bar-session-ref.v1":
        return False
    if reference.get("source_kind") != "bar":
        return False
    manifest = reference.get("paging_manifest")
    if not isinstance(manifest, Mapping):
        return False
    return (
        manifest.get("schema_version") in {
            MANIFEST_SCHEMA, PAGED_BAR_MANIFEST_SCHEMA_VERSION,
        }
        and manifest.get("terminal_kind") == BAR_TERMINAL_REQUESTED_HORIZON
    )
