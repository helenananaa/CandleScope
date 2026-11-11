"""Shared host-local references to an already published SDK projection.

These are neither wire requests nor mathematical checkpoints. Indicator
ownership and generic process supervision use the same immutable reference
without importing either subsystem's implementation into the other.
"""
from dataclasses import dataclass

from candlescope_plugin_sdk import RenderOutput


@dataclass(frozen=True, slots=True)
class RuntimeOutputReference:
    owner_epoch: str
    generation: int
    stream: str
    revision: str


@dataclass(frozen=True, slots=True)
class RuntimeOutputSnapshot:
    reference: RuntimeOutputReference
    output: RenderOutput
