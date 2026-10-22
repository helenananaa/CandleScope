"""Historical OHLC observations over a persistent external Pine stream.

The application coordinator supplies a kernel, frozen wire and restored stream.
It still owns durable pairing with its ledger and account event cursor.
"""
from copy import deepcopy

from .errors import BacktestError
from .external import account_feedback_profit
from .pine_request_updates import from_wire, pass_observations, validate_replay
from .pine_workbench import check_risk_response


class HistoryTickClock:
    def __init__(self, stream, kernel, orders, wire, *, state=None):
        self.stream, self.kernel, self.orders, self.wire = stream, kernel, orders, wire
        self.feed = from_wire(wire)
        self.positions = {bar["time"]: index for index, bar in enumerate(wire["bars"])}
        state = deepcopy(state or {})
        self.groups, self.accounts, self.history = (state.get(key,[]) for key in ("groups","accounts","history"))
        if self.feed is not None and state:
            validate_replay(self.feed,state.get("request_feed"),pass_observations(self.groups,scheduled=True))
        self.visible = None
        self.index = None

    def vertex(self, source, point, ordinal):
        index = self.positions[int(source.payload["open_time_ms"])//1000]
        if index < self.stream.input_skip:
            return
        canonical = self.wire["bars"][index]
        if ordinal == 0:
            self.stream.begin(canonical, bar_state="historical")
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
        result = self.stream.observe(observation)
        current = result["intents"]
        if len(current)>64:
            raise BacktestError("BUDGET_EXCEEDED", "at most 64 intents per Pine observation")
        self.groups[-1].append(deepcopy(observation))
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
            self.stream.commit()
        else:
            self.groups.append([])
            account = self.kernel.account
            self.accounts.append(dict(time=self.wire["bars"][index]["time"],position_size=float(account.position_qty),
                position_avg_price=None if account.entry_price is None else float(account.entry_price),
                equity=float(account.equity()),initial_capital=float(self.kernel.initial_balance),
                netprofit=float(account_feedback_profit(account,self.kernel.initial_balance)),openprofit=float(account.unrealized())))
        return []

    def output(self):
        result = self.stream.output()
        return {**result,"raw_output":result["output"],"graphics":result["output"].get("plots",[])}
