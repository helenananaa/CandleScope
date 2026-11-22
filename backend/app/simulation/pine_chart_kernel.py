"""Compatibility name: the Host bar kernel on its Pine chart bar clock (ADR-BACKTEST-015 P6b).

The chart bar lifecycle runs inside ``SimulationKernel`` (``ohlc_path``). P6c moves callers
to ``SimulationKernel(bar_clock=PINE_CHART)`` and removes this module.
"""
from dataclasses import dataclass

from .ohlc_path import CHART_CONTRACT as CONTRACT, PINE_CHART
from .pine_bar_kernel import PineBarKernel

__all__ = ["CONTRACT", "PineChartBarKernel"]


@dataclass(slots=True)
class PineChartBarKernel(PineBarKernel):
    bar_clock: str = PINE_CHART
