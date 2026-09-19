from candlescope_backtest_sdk import Observation, StrategyContext, TargetPosition


class Strategy:
    market_batch_protocol = "candlescope.python-market-batch/1"

    @staticmethod
    def calculate_batch(batch, parameters):
        # Retain scalar float summation order, partial-window divisors and ties.
        # Each output reads only its prefix, including supplied past context.
        fast, slow = int(parameters["fast"]), int(parameters["slow"])
        closes = tuple(map(float, batch.close))
        targets = []
        for row in range(batch.context_rows, len(closes)):
            if row - batch.context_rows < batch.warmup_rows:
                targets.append(None)
                continue
            end = row + 1
            fast_value = sum(closes[max(0, end-fast):end]) / fast
            slow_value = sum(closes[max(0, end-slow):end]) / slow
            targets.append("1" if fast_value > slow_value else "-1")
        return tuple(targets)

    def prepare(self, context: StrategyContext) -> None:
        self.fast = int(context.parameters["fast"])
        self.slow = int(context.parameters["slow"])
        self.closes: list[str] = []

    def warmup(self, observation: Observation) -> None:
        self.closes.append(observation.bar.close)
        del self.closes[:-max(self.fast, self.slow)]

    def step(self, observation: Observation) -> TargetPosition:
        self.closes.append(observation.bar.close)
        del self.closes[:-max(self.fast, self.slow)]
        fast = sum(map(float, self.closes[-self.fast :])) / self.fast
        slow = sum(map(float, self.closes[-self.slow :])) / self.slow
        return TargetPosition(quantity="1" if fast > slow else "-1")

    def on_execution_report(self, report) -> None:
        return None

    def snapshot(self) -> dict:
        return {"closes": list(self.closes)}

    def restore(self, payload: dict) -> None:
        # Accept the previous full-history snapshot while retaining only what
        # the next decision needs. Parameters come from prepare().
        self.closes = [str(value) for value in payload["closes"][-max(self.fast, self.slow):]]

    def close(self) -> None:
        return None
