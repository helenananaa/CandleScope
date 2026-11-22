"""Compatibility name: the Host bar kernel on its Pine V2 path clock (ADR-BACKTEST-015 P6b).

Causal V2 account events and shared bar capacity run inside ``SimulationKernel``
(``ohlc_path``). P6c moves callers to ``SimulationKernel(bar_clock=PINE_V2)`` and removes
this module.
"""
from dataclasses import dataclass

from .ohlc_path import AUXILIARY, PINE_V2, V2_CONTRACT as CONTRACT
from .pine_chart_kernel import PineChartBarKernel

__all__ = ["AUXILIARY", "CONTRACT", "PineV2BarKernel"]


@dataclass(slots=True)
class PineV2BarKernel(PineChartBarKernel):
    bar_clock: str = PINE_V2
