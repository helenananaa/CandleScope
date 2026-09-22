from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def fingerprint(value: object) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class PreparationError(ValueError):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        self.code, self.retryable = code, retryable
        super().__init__(message)


class Requirement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    exchange: str = Field(min_length=1, max_length=40, pattern=r"^[a-z0-9_-]+$")
    market_type: str = Field(min_length=1, max_length=40, pattern=r"^[a-z0-9_-]+$")
    symbol: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_:/.-]+$")
    role: Literal["BARS", "TRADES", "FUNDING", "MARK_PRICE", "INSTRUMENT_RULES"] = "BARS"
    interval: str = "1m"
    # Half-open boundaries. Warmup is resolved before submission; never move
    # these endpoints as retries cross the current time.
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)

    @model_validator(mode="after")
    def valid_range(self):
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be later than start_ms")
        if self.end_ms - self.start_ms > 366 * 86_400_000:
            raise ValueError("a requirement may span at most 366 days")
        return self


class PreparationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    idempotency_key: str = Field(min_length=8, max_length=128)
    consumer: Literal["REPLAY", "STRATEGY", "PREFETCH"]
    requirements: list[Requirement] = Field(min_length=1, max_length=32)
    # Frozen input to the consumer adapter, not arbitrary executable code.
    intent: dict = Field(default_factory=dict)
    max_bytes: int = Field(default=512 * 1024 * 1024, ge=1024, le=16 * 1024**3)
    progressive: bool = False

    @model_validator(mode="after")
    def bounded_intent(self):
        if len(canonical(self.intent)) > 256_000:
            raise ValueError("intent exceeds 256 KB")
        return self

    def identity(self) -> str:
        return fingerprint(self.model_dump(exclude={"idempotency_key"}))


def split_requirement(requirement: Requirement) -> list[Requirement]:
    """Canonical day boundaries allow partially overlapping consumers to reuse work.

    Boundary fragments stay exact: never fetch a whole day beyond user intent.
    """
    result = []
    start = requirement.start_ms
    while start < requirement.end_ms:
        end = min(requirement.end_ms, (start // 86_400_000 + 1) * 86_400_000)
        result.append(requirement.model_copy(update={"start_ms": start, "end_ms": end}))
        start = end
    return result
