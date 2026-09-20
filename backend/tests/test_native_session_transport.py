import sys
import threading
import pytest
from app.backtest.native_session import SessionWorker


def test_timeout_reaps_persistent_child():
    script = """import json,sys,time
request=json.loads(sys.stdin.readline())
print(json.dumps({'ok':True,'identity':request['identity'],'supported':True}),flush=True)
sys.stdin.readline()
time.sleep(20)
"""
    worker = SessionWorker({"command": [sys.executable, "-u", "-c", script]}, {"identity": {}}, threading.Event())
    with pytest.raises(ValueError, match="NATIVE_TIMEOUT"):
        worker.request({"operation": "advance", "target": 1}, threading.Event(), timeout=.1)
    assert worker.process.poll() is not None
    assert worker.stderr.closed


def test_cancelled_session_reaps_child():
    script = """import json,sys,time
request=json.loads(sys.stdin.readline())
print(json.dumps({'ok':True,'identity':request['identity'],'supported':True}),flush=True)
sys.stdin.readline()
time.sleep(20)
"""
    event = threading.Event()
    worker = SessionWorker({"command": [sys.executable, "-u", "-c", script]}, {"identity": {}}, event)
    event.set()
    with pytest.raises(ValueError, match="NATIVE_CANCELLED"):
        worker.advance(1, event)
    assert worker.process.poll() is not None


@pytest.mark.parametrize("cancel", [False, True])
def test_evaluator_timeout_or_cancel_reaps_child_without_open_handshake(cancel):
    event = threading.Event()
    worker = SessionWorker({"command": [sys.executable, "-u", "-c",
        "import sys,time; sys.stdin.readline(); time.sleep(20)"]}, {"identity": {}}, event, evaluator=True)
    if cancel:
        event.set()
    with pytest.raises(ValueError, match="NATIVE_CANCELLED" if cancel else "NATIVE_TIMEOUT"):
        worker.request({"operation": "execute"}, event, timeout=.1)
    assert worker.process.poll() is not None and worker.stderr.closed
