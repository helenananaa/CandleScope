"""Common data lifecycle owner; constructing it opens no live market feeds."""
from __future__ import annotations

from typing import TYPE_CHECKING

from .strategy import StrategyDataManager
from .account import ReadOnlyAccountDataManager
from .trading import TradingAccountDataManager

if TYPE_CHECKING:
    from app.backtest.service import BacktestService
    from app.backtest.runtime import BacktestRuntime


class DataManagerCore:
    def __init__(self) -> None:
        self.strategy: StrategyDataManager | None = None
        self.readonly_account: ReadOnlyAccountDataManager | None = None
        self.trading: TradingAccountDataManager | None = None

    def bind_trading(self, service) -> TradingAccountDataManager:
        if self.trading is not None:
            if self.trading.service is not service:
                raise RuntimeError("trading account service is already bound")
            return self.trading
        self.trading = TradingAccountDataManager(service)
        return self.trading

    def close_trading(self) -> None:
        if self.trading is not None:
            self.trading.close()

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

    def bind_readonly_account(self, service) -> ReadOnlyAccountDataManager:
        if self.readonly_account is not None:
            if self.readonly_account.service is not service:
                raise RuntimeError("read-only account service is already bound")
            return self.readonly_account
        self.readonly_account = ReadOnlyAccountDataManager(service)
        return self.readonly_account

    def close_readonly_account(self) -> None:
        if self.readonly_account is not None:
            self.readonly_account.close()
