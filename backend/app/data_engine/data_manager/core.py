"""Common data lifecycle owner; constructing it opens no live market feeds."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .strategy import StrategyDataManager

if TYPE_CHECKING:
    from app.backtest.service import BacktestService
    from app.backtest.runtime import BacktestRuntime


class DataManagerCore:
    def __init__(self) -> None:
        self.strategy: StrategyDataManager | None = None

    def bind_strategy(self, service: BacktestService, runtime: BacktestRuntime | None = None) -> StrategyDataManager:
        if self.strategy is not None:
            if self.strategy.service is not service or self.strategy.runtime is not runtime:
                raise RuntimeError("strategy service is already bound to this data manager")
            return self.strategy
        self.strategy = StrategyDataManager(service, runtime=runtime)
        return self.strategy

    def close_strategy(self) -> None:
        if self.strategy is not None:
            self.strategy.close()
