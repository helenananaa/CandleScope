"""Exchange-neutral subscription choices; channel contracts define the guarantee."""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ContinuityPolicy:
    """Strict waits for proven channel data; gap_aware exposes source gaps.

    The wait budget is never extended by repair retries. Bars use source gap
    detection time; ID batches use the consumer's observation of the missing
    range. Snapshot channels guarantee current state, not every transition.
    Terminal failure requires a fresh snapshot and a new subscription.
    """

    mode: str = "strict"
    max_wait_seconds: float = 10.0

    def __post_init__(self) -> None:
        if self.mode not in {"strict", "gap_aware"}:
            raise ValueError("continuity mode must be strict or gap_aware")
        if not math.isfinite(self.max_wait_seconds) or self.max_wait_seconds <= 0:
            raise ValueError("max_wait_seconds must be finite and positive")

    @classmethod
    def resolve(cls, value: ContinuityPolicy | str) -> ContinuityPolicy:
        return value if isinstance(value, cls) else cls(mode=value)



class ContinuityUnsupported(ValueError):
    """The provider cannot prove the continuity requested by this consumer."""

    code = "CONTINUITY_UNSUPPORTED"


def observational_policy(value: ContinuityPolicy | str | None, *, channel: str):
    policy = ContinuityPolicy.resolve(value) if value is not None else None
    if policy is not None and policy.mode == "strict":
        raise ContinuityUnsupported(
            f"{channel} is observational or sampled; strict source completeness "
            "cannot be proven. Choose gap_aware to accept this source quality."
        )
    return policy
