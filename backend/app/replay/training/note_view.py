"""The client-selected view for reading or writing a replay annotation."""

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ReplayNoteView:
    training: bool = False
    review_id: str | None = None
    review_revision: int | None = None

    def matches(self, context: Mapping[str, object]) -> bool:
        if self.training:
            return context["reviewId"] is None
        if self.review_id is None:
            return True  # Legacy callers still follow the latest Review.
        return (context["reviewId"], context["reviewRevision"]) == (self.review_id, self.review_revision)
