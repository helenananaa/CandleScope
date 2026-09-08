"""Transport close can win the race before receive() sees disconnect."""
import asyncio
import json

import pytest
from starlette.websockets import WebSocket, WebSocketDisconnect

from app.api.v1.stream_market import stream_market
from app.api.v1.stream_utils import send_json_with_timeout, send_text_with_timeout
from tests.test_market_stream_api import _MarketStreamDataManager, _stream

CLOSED = "Unexpected ASGI message 'websocket.send', after sending 'websocket.close' or response already completed."


@pytest.mark.parametrize('sender,payload', [(send_json_with_timeout, {'type': 'update'}),
                                           (send_text_with_timeout, 'pong')])
@pytest.mark.parametrize('closed_error', [CLOSED, 'Cannot call "send" once a close message has been sent.'])
def test_transport_closed_send_is_disconnect(sender, payload, closed_error):
    async def scenario():
        async def receive():
            return {'type': 'websocket.connect'}
        async def send(message):
            if message['type'] == 'websocket.send':
                raise RuntimeError(closed_error)
        ws = WebSocket({'type': 'websocket'}, receive, send)
        await ws.accept()
        with pytest.raises(WebSocketDisconnect):
            await sender(ws, payload)
    asyncio.run(scenario())


def test_unrelated_send_error_is_not_hidden():
    async def scenario():
        async def receive():
            return {'type': 'websocket.connect'}
        async def send(message):
            if message['type'] == 'websocket.send':
                raise RuntimeError('unexpected serialization invariant')
        ws = WebSocket({'type': 'websocket'}, receive, send)
        await ws.accept()
        with pytest.raises(RuntimeError, match='serialization invariant'):
            await send_json_with_timeout(ws, {'type': 'update'})
    asyncio.run(scenario())


def test_market_forward_close_race_releases_leases_and_tasks():
    async def scenario():
        messages = asyncio.Queue()
        messages.put_nowait({'type': 'websocket.connect'})
        messages.put_nowait({'type': 'websocket.receive', 'text': json.dumps({
            'action': 'subscribe', 'streams': [_stream('mark_price')],
        })})
        sent = []
        async def send(message):
            if message['type'] == 'websocket.send':
                payload = json.loads(message['text'])
                sent.append(payload['type'])
                if payload['type'] == 'update':
                    raise RuntimeError(CLOSED)
        ws = WebSocket({'type': 'websocket'}, messages.get, send)
        await ws.accept()
        dm = _MarketStreamDataManager()
        await asyncio.wait_for(stream_market(ws, dm), timeout=2)
        assert sent == ['connected', 'subscribed', 'snapshot', 'update']
        assert len(dm.release_calls) == 1
        assert not dm._leases
        assert dm.hub.diagnostics()['active_subscribers'] == 0
        assert not [task for task in asyncio.all_tasks()
                    if task is not asyncio.current_task() and task.get_name().startswith('market-ws-')]
    asyncio.run(scenario())
