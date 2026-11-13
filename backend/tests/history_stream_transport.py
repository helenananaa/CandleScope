"""Controlled native records, not replacement fetch/reconcile results."""
from app.data_engine.ingestion.models import RawMessage, DataSource, StreamType
from app.data_engine.interval_policy import parse_interval_ms


class IntervalTransport:
    def __init__(self):
        self.calls = []

    async def http_fetch(self, request):
        self.calls.append(request)
        width = parse_interval_ms(request.descriptor.interval)
        first = (request.start_ms+width-1)//width*width
        last = request.end_ms
        return [RawMessage(payload=[at,'100','102','99','101',str(width//60_000),
            at+width-1,str(2*width//60_000),width//60_000,str(width//60_000),str(2*width//60_000),'0'],
            source=DataSource.HTTP,stream_type=StreamType.KLINE,received_at_ms=last,
            endpoint='https://api.binance.com')
            for at in list(range(first,last+1,width))[:request.limit]]
