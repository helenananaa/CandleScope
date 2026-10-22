"""Discard tentative chart ledgers until observed Pine windows are stable."""
from copy import deepcopy

from .errors import BacktestError
from .pine_stream import WINDOW_FEEDBACK_CONTRACT, WindowRebaseRequired
from .strategy.pine_engine import PineEngineProvider


class ChartWindowDiscovery:
    def __init__(self,provider,session,kernel,planner,*,enabled,new_planner,deadline,control):
        current=provider
        while not isinstance(current,PineEngineProvider) and hasattr(current,"provider"):
            current=current.provider
        self.provider=current
        self.enabled=bool(enabled and isinstance(current,PineEngineProvider)
            and current.runtime_identity.get("window_feedback_contract")==WINDOW_FEEDBACK_CONTRACT)
        self.session,self.kernel,self.planner=session,kernel,planner
        self.new_planner=new_planner
        self.deadline,self.control=deadline,control
        if self.enabled:
            self.initial_session=deepcopy(session.snapshot())
            self.initial_kernel=deepcopy(kernel.snapshot())
            self.base_execution_reporter=planner.orders.execution_reporter
            self.base_market_observer=kernel.market_observer

    def pending(self):
        stream=self.provider.stream if self.enabled else None
        return bool(stream is not None and stream.last.get("window_status",{}).get("requires_discovery"))

    def execute(self,run,reset_bookkeeping):
        for _attempt in range(64):
            if self.enabled: self.control()
            try:
                result=run()
            except WindowRebaseRequired:
                if not self.pending(): raise
                self._reset(seal=False)
            else:
                if not self.pending(): return result
                self._reset(seal=True)
            reset_bookkeeping()
        raise BacktestError("BUDGET_EXCEEDED","at most 64 observed chart window executions")

    def _reset(self,*,seal):
        self.control()
        stream=self.provider.stream
        stream.deadline=self.deadline
        if seal and stream.bar_open:
            stream.commit()
        stream.rebase(seal=seal)
        environment=deepcopy(self.provider._stream_environment)
        # Retain the freshly reset evaluator and its verified plan transcript;
        # ordinary provider restore resets all Host-facing observations/feed.
        self.provider.stream=None
        try:
            self.session.restore(deepcopy(self.initial_session))
            self.kernel.restore(deepcopy(self.initial_kernel))
            # A trial may have frozen order/risk capabilities already. Reusing
            # that planner would either retain state or relax its restore guard.
            self.planner=self.new_planner()
            self.kernel.execution_reporter=self.base_execution_reporter
            self.kernel.market_observer=self.base_market_observer
            self.planner.bind_kernel(self.kernel)
            self.provider.stream=stream
            self.provider._stream_environment=environment
            stream.cancelled=self.provider.cancelled
        except Exception:
            stream.close()
            raise
