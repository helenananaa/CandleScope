import sys
import threading
import pytest
from app.backtest.native_session import SessionWorker
from app.backtest.native import digest


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
    assert not worker._io_thread.is_alive()


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
    assert not worker._io_thread.is_alive()


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
    assert not worker._io_thread.is_alive()


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


@pytest.mark.parametrize("contract", [False, True])
def test_real_worker_binds_full_identity_before_references_and_preserves_public_responses(contract):
    identity = {"engine": "unchanged", "nested":{"value":"unchanged"},
                **({"session_identity": "candlescope.session-identity/1"} if contract else {})}
    script = '''import json,sys
for index,line in enumerate(sys.stdin):
    request=json.loads(line)
    if index==0 or "identity_ref" not in request:
        assert "identity" in request
        response={"ok":True,"identity":request["identity"],"index":index}
    else:
        assert "identity" not in request
        response={"ok":True,"identity_ref":request["identity_ref"],"index":index}
    print(json.dumps(response),flush=True)
'''
    worker = SessionWorker({"command": [sys.executable, "-u", "-c", script]},
                           {"identity": identity}, threading.Event(), evaluator=True)
    try:
        for index in range(3):
            response = worker.request({"operation": "execute"}, threading.Event())
            assert response == {"ok": True, "identity": identity, "index": index}
            response["identity"]["nested"]["value"] = "caller mutation"
    finally:
        worker.close()


@pytest.mark.parametrize("failure", ["changed", "mixed", "unbound", "unnegotiated"])
def test_invalid_wire_identity_reference_reaps_the_actual_child(failure):
    identity = {"engine": "unchanged", **({"session_identity": "candlescope.session-identity/1"}
                                          if failure != "unnegotiated" else {})}
    reference = digest(identity)
    script = f'''import json,sys
for index,line in enumerate(sys.stdin):
    request=json.loads(line)
    if index==0 and {failure!r}!="unbound":
        result={{"ok":True,"identity":request["identity"]}}
    else:
        result={{"ok":True,"identity_ref":{reference!r} if {failure!r}!="changed" else "sha256:changed"}}
        if {failure!r}=="mixed":result["identity"]={identity!r}
    print(json.dumps(result),flush=True)
'''
    worker = SessionWorker({"command": [sys.executable, "-u", "-c", script]},
                           {"identity": identity}, threading.Event(), evaluator=True)
    if failure != "unbound":
        worker.request({"operation": "execute"}, threading.Event())
    with pytest.raises(ValueError, match="NATIVE_IDENTITY_MISMATCH"):
        worker.request({"operation": "execute"}, threading.Event())
    assert worker.process.poll() is not None and worker.stderr.closed


def test_reused_transport_preserves_ordered_responses_and_closes_its_thread():
    script = '''import json,sys
for line in sys.stdin:
    request=json.loads(line)
    print(json.dumps(dict(ok=True,identity=request['identity'],ordinal=request['ordinal'])),flush=True)
'''
    worker = SessionWorker({"command":[sys.executable,"-u","-c",script]},
                           {"identity":{}},threading.Event(),evaluator=True)
    transport = worker._io_thread
    try:
        for ordinal in range(500):
            assert worker.request({"operation":"execute","ordinal":ordinal},threading.Event())["ordinal"] == ordinal
            assert worker._io_thread is transport and transport.is_alive()
    finally:
        worker.close()
    assert not transport.is_alive()
    assert worker.process.poll() is not None
    with pytest.raises(ValueError,match="session is closed"):
        worker.request({"operation":"execute","ordinal":500},threading.Event())


def test_concurrent_callers_cannot_mix_inflight_protocol_responses():
    script = '''import json,sys,time
for line in sys.stdin:
    request=json.loads(line)
    time.sleep(.001)
    print(json.dumps(dict(ok=True,identity=request['identity'],ordinal=request['ordinal'])),flush=True)
'''
    worker = SessionWorker({"command":[sys.executable,"-u","-c",script]},
                           {"identity":{}},threading.Event(),evaluator=True)
    failures = []
    def call(ordinal):
        try:
            assert worker.request({"operation":"execute","ordinal":ordinal},threading.Event())["ordinal"] == ordinal
        except Exception as exc:
            failures.append(exc)
    try:
        threads = [threading.Thread(target=call,args=(ordinal,)) for ordinal in range(12)]
        for thread in threads: thread.start()
        for thread in threads:
            thread.join(timeout=5)
            assert not thread.is_alive()
        assert failures == []
    finally:
        worker.close()
    assert not worker._io_thread.is_alive()
