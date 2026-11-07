"""Versioned chart projection positions, distinct from standalone history."""
from pydantic import BaseModel, ConfigDict, Field

from .calculation_owner import CalculationOwnerError


class CalculationReference(BaseModel):
    model_config = ConfigDict(extra='forbid')

    schemaVersion: int = Field(strict=True, ge=1, le=1)
    domainId: str = Field(strict=True, pattern=r'^[a-f0-9]{32}$')
    generation: int = Field(strict=True, ge=1)
    sequence: int = Field(strict=True, ge=1)


class CalculationRangeRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    calculation: CalculationReference
    clientId: str = Field(strict=True, min_length=1, max_length=256)
    start: int = Field(strict=True, gt=0)
    end: int = Field(strict=True, gt=0)
    rebuild: bool = Field(default=False, strict=True)
    complete: bool = Field(default=False, strict=True)


def reference_for(owner, cursor=None):
    current = cursor or owner.cursor
    if current is None:
        raise CalculationOwnerError('INDICATOR_CALCULATION_REBUILD_REQUIRED')
    return CalculationReference(schemaVersion=1, domainId=owner.plan.owner_id,
                                generation=current.generation, sequence=current.sequence)


def check_reference(owner, reference: CalculationReference, *, allow_earlier=False):
    current = reference_for(owner)
    if (reference.domainId != current.domainId
            or reference.generation > current.generation or reference.sequence > current.sequence
            or (not allow_earlier and reference != current)):
        raise CalculationOwnerError('INDICATOR_CALCULATION_CHANGED')


def projection_position(owner, cursor):
    return {**reference_for(owner, cursor).model_dump(), 'view':'current-projection',
        'origin':owner.plan.start, 'observedThrough':cursor.observed_through,
        'closedThrough':cursor.closed_through, 'inputRevision':cursor.input_revision}
