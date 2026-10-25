"""Historical OHLC observations over a persistent external Pine stream.

The application coordinator supplies a kernel, frozen wire and restored stream.
It still owns durable pairing with its ledger and account event cursor.
"""
from copy import deepcopy

from .errors import BacktestError
from .external import account_feedback_profit
from .pine_request_updates import from_wire, pass_observations, validate_replay
from .pine_workbench import check_risk_response
from .pine_stream import seal_observation_group


class HistoryTickClock:
    def __init__(self, stream, kernel, orders, wire, *, state=None, _compact_groups=False, _owned_state=False,
                 _chain_commits=True):
        self.stream, self.kernel, self.orders, self.wire = stream, kernel, orders, wire
        self._compact_groups = _compact_groups
        self._chain_commits = _chain_commits
        self._pending_commit = False
        self.feed = from_wire(wire)
        self.positions = {bar["time"]: index for index, bar in enumerate(wire["bars"])}
        restoring = bool(state)
        state = {key:value for key,value in (state or {}).items()
                 if key in {"groups","accounts","history","request_feed"}}
        if not _owned_state:
            state = deepcopy(state)
        self.groups, self.accounts, self.history = (state.get(key,[]) for key in ("groups","accounts","history"))
        if self.feed is not None and restoring:
            validate_replay(self.feed,state.get("request_feed"),pass_observations(self.groups,scheduled=True))
        self.visible = None
        self.index = None

    def vertex(self, source, point, ordinal):
        index = self.positions[int(source.payload["open_time_ms"])//1000]
        if index < self.stream.input_skip:
            return
        canonical = self.wire["bars"][index]
        if ordinal == 0:
            self.visible = {**canonical, "high": canonical["open"], "low": canonical["open"],
                            "close": canonical["open"], "volume": 0}
            self.index = index
            self.groups.append([])
            self.accounts.append(None)
        if index != self.index or ordinal != len(self.groups[-1]):
            raise BacktestError("EXTERNAL_PROTOCOL_ERROR", "historical vertex sequence differs")
        self.orders.feedback()
        account = self.kernel.account
        feedback = dict(time=canonical["time"], position_size=float(account.position_qty),
            position_avg_price=None if account.entry_price is None else float(account.entry_price),
            equity=float(account.equity()), initial_capital=float(self.kernel.initial_balance),
            netprofit=float(account_feedback_profit(account,self.kernel.initial_balance)), openprofit=float(account.unrealized()))
        price = float(point.payload["price"])
        self.visible.update(high=max(self.visible["high"],price),low=min(self.visible["low"],price),
                            close=price,volume=canonical["volume"]*(ordinal+1)/4)
        evaluation = dict(bar=deepcopy(self.visible),account=feedback,
                          event_time_ms=point.event_time_ms,confirmed=ordinal==3)
        if self.feed is not None:
            # Historical requested contexts use the completed chart boundary at
            # every synthetic vertex; the account/order path remains progressive.
            observed = source.event_time_ms
            evaluation.update(request_observed_at_ms=observed,request_updates=self.feed.advance(observed))
        observation = dict(evaluation=evaluation,context=dict(bar_state="historical",trigger="historical_tick",is_new=True))
        # Beginning a bar has no Host callback or account mutation. Share its
        # transport with the first observation, retaining both checked replies
        # and journal entries. Observe stays last so request-window discovery
        # returns control before any further command or Host matching occurs.
        result = (self.stream.begin_and_observe(canonical,bar_state="historical",observation=observation,_owned=True,
                    _commit_previous=self._pending_commit)
                  if ordinal == 0 else self.stream.observe(observation,_owned=True))
        self._pending_commit = False
        current = result["intents"]
        if len(current)>64:
            raise BacktestError("BUDGET_EXCEEDED", "at most 64 intents per Pine observation")
        # Bar, feedback and requested deltas are owned snapshots created above;
        # PineStream encodes its immutable command before returning.
        self.groups[-1].append(observation)
        self.accounts[-1] = feedback
        self.history.extend(current)
        self.orders.configure(result.get("pyramiding",1))
        check_risk_response(self.orders,self.wire,result)
        translated = self.orders.translate(current,point.sequence)
        self.kernel.decisions.append(dict(sequence=point.sequence,watermark_ms=point.event_time_ms,
            intents=translated,signal_bar=index,pass_index=ordinal,trigger="HISTORICAL_TICK"))
        self.kernel._enqueue_many(translated,current_sequence=point.sequence)
        if ordinal<3:
            self.kernel.match_observation_markets(point)

    def close(self, source):
        index = self.positions[int(source.payload["open_time_ms"])//1000]
        if index >= self.stream.input_skip:
            if self._chain_commits:
                # Commit consumes no account input and emits no intents. Keep
                # its original command position before the next begin/observe;
                # only transport is deferred, never observations or matching.
                self._pending_commit = True
            else:
                self.stream.commit()
        else:
            self.groups.append([])
            account = self.kernel.account
            self.accounts.append(dict(time=self.wire["bars"][index]["time"],position_size=float(account.position_qty),
                position_avg_price=None if account.entry_price is None else float(account.entry_price),
                equity=float(account.equity()),initial_capital=float(self.kernel.initial_balance),
                netprofit=float(account_feedback_profit(account,self.kernel.initial_balance)),openprofit=float(account.unrealized())))
        if self._compact_groups:
            seal_observation_group(self.groups)
        return []

    def flush_commit(self):
        if self._pending_commit:
            self.stream.commit()
            self._pending_commit = False

    def output(self):
        # Every report, discovery seal and durable checkpoint sees a closed
        # stream, including a midpoint or the final chart bar.
        self.flush_commit()
        result = self.stream.output()
        return {**result,"raw_output":result["output"],"graphics":result["output"].get("plots",[])}
