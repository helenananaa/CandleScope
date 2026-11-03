"""Common data lifecycle owner; constructing it opens no live market feeds."""
from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from .strategy import StrategyDataManager
from .account import ReadOnlyAccountDataManager
from .replay import ReplayDataManager

if TYPE_CHECKING:
    from app.backtest.service import BacktestService
    from app.backtest.runtime import BacktestRuntime


class DataManagerCore:
    def __init__(self) -> None:
        self.strategy: StrategyDataManager | None = None
        self.readonly_account: ReadOnlyAccountDataManager | None = None
        self.replay: ReplayDataManager | None = None
        self._history_studies = None
        self._study_lock = threading.Lock()

    def bind_replay(self, service, runtime=None) -> ReplayDataManager:
        if self.replay is not None:
            if self.replay.service is not service or self.replay.runtime is not runtime:
                raise RuntimeError("replay service is already bound to this data manager")
            return self.replay
        self.replay = ReplayDataManager(service, runtime)
        return self.replay

    def close_replay(self) -> None:
        if self.replay is not None:
            self.replay.close()

    async def shutdown_replay(self, *, step_timeout: float = 5.0) -> None:
        if self.replay is not None:
            await self.replay.shutdown(step_timeout=step_timeout)

    def history_studies(self, path):
        # No database or public market transport opens during construction.
        # The repository uses short transaction-owned connections, so it has
        # no resident writer/socket requiring a shutdown ordering dependency.
        from app.history_studies.repository import HistoryStudyRepository
        with self._study_lock:
            if self._history_studies is None:
                self._history_studies = HistoryStudyRepository(path)
            elif self._history_studies.path != path:
                raise RuntimeError("History studies are already bound to another profile")
            return self._history_studies

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
