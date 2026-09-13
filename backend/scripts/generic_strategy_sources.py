"""Ordinary, unchanged V1 script workloads; no batch/purity declarations."""

_BASE = '''from candlescope_backtest_sdk import TargetPosition, OrderIntent
class Strategy:
 def prepare(self, context):
  self.seen = 0
  self.fills = 0
  self.last = 0.0
  self.mode = 1
 def warmup(self, observation):
  self.seen += 1
 def on_execution_report(self, report):
  if report.get("fill"):
   self.fills += 1
 def snapshot(self):
  return {"seen":self.seen, "fills":self.fills, "last":self.last, "mode":self.mode}
 def restore(self, state):
  self.seen, self.fills, self.last, self.mode = state["seen"], state["fills"], state["last"], state["mode"]
 def close(self):
  pass
'''

SOURCES = {
    "EMPTY": _BASE + ''' def step(self, observation):
  self.seen += 1
  return None
''',
    "STATE": _BASE + ''' def step(self, observation):
  self.seen += 1
  current = float(observation.bar.close)
  if self.seen % 79 == 1:
   self.mode = 1 if current > self.last else -1
   self.last = current
   return TargetPosition(str(self.mode))
  self.last = current
  return None
''',
    "FEEDBACK": _BASE + ''' def step(self, observation):
  self.seen += 1
  if self.seen % 64 == 1:
   return TargetPosition("1" if self.fills % 2 == 0 else "-1")
  return None
''',
    "ORDERS": _BASE + ''' def step(self, observation):
  self.seen += 1
  if self.seen % 50 == 1:
   self.mode = -self.mode
   return OrderIntent("BUY" if self.mode < 0 else "SELL", "MARKET", "1")
  return None
''',
}
