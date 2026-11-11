"""Time and event visibility for saved replay annotations."""

from collections.abc import Mapping


def original_note_timeline(context: Mapping[str, object]) -> int:
    # An original saved against event N was written after N. Live readers
    # include it immediately; Review event N must show its prior state.
    return int(context["timelineSequence"]) - int(context["reviewId"] is not None)
