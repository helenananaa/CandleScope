"""Compatibility name: the Host bar kernel on its Pine OHLC path clock (ADR-BACKTEST-015 P6b).

The path matcher runs inside ``SimulationKernel`` (``ohlc_path``). P6c moves callers to
``SimulationKernel(bar_clock=PINE_PATH)`` and removes this module.
"""
from dataclasses import dataclass

from .kernel import SimulationKernel
from .ohlc_path import LIVE, PATH_CONTRACT as CONTRACT, PATH_MODEL as MODEL, PINE_PATH

__all__ = ["CONTRACT", "LIVE", "MODEL", "PineBarKernel"]


@dataclass(slots=True)
class PineBarKernel(SimulationKernel):
    bar_clock: str = PINE_PATH
