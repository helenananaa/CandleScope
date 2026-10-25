import math
from app.market_dataset.snapshot import MarketEvent

def events(count=400):
    return tuple(MarketEvent(sequence=i, event_time_ms=(i // 2)*60000, role="BARS", payload={
        "open": str(round(100 + 10*math.sin(i/3), 5)),
        "high": str(round(100 + 10*math.sin(i/3), 5)),
        "low": str(round(100 + 10*math.sin(i/3), 5)),
        "close": str(round(100 + 10*math.sin(i/3), 5)), "volume": "10000",
    }) for i in range(1, count+1))
