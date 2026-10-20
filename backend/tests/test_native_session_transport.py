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


def test_concurrent_close_reaps_child_and_releases_all_streams_once():
    worker = SessionWorker({"command": [sys.executable, "-u", "-c", "import time; time.sleep(20)"]},
        {"identity": {}}, threading.Event(), evaluator=True)
    barrier = threading.Barrier(3)
    failures = []
    def close():
        barrier.wait()
        try:
            worker.close()
        except Exception as exc:
            failures.append(exc)
    threads = [threading.Thread(target=close) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=5)
        assert not thread.is_alive()
    assert failures == []
    assert worker.process.poll() is not None
    assert all(stream.closed for stream in (worker.process.stdin, worker.process.stdout, worker.stderr))
    worker.close()


def test_terminated_pipe_close_error_does_not_mask_timeout_or_skip_other_streams():
    worker = SessionWorker({"command": [sys.executable, "-u", "-c", "import time; time.sleep(20)"]},
        {"identity": {}}, threading.Event(), evaluator=True)
    stream = worker.process.stdin
    class BrokenClose:
        @property
        def closed(self):
            return stream.closed
        def close(self):
            stream.close()
            raise OSError(22, "controlled terminated pipe close")
    worker.process.stdin = BrokenClose()
    worker.close()
    assert worker.process.poll() is not None
    assert worker.process.stdout.closed and worker.stderr.closed and stream.closed
    assert worker.close_errors == [{"stream": "stdin", "errno": 22}]
    worker.close()
