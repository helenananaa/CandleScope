import os
import signal
import time

import pytest

from app.core.process_lane import SerialProcessLane


def echo(value):
    return value


def make_bytes(count):
    return bytes(count)


def test_byte_admission_and_output_limit_preserve_framing():
    lane = SerialProcessLane(echo, name='test-byte-admission', max_message_bytes=1024)
    try:
        assert lane.call('ready') == 'ready'
        with pytest.raises(ValueError, match='byte budget'):
            lane.call(bytes(2048))
        assert lane.call('after rejection') == 'after rejection'
        state = lane.snapshot()
        assert state['calls'] == 3
        assert 0 < state['sent_bytes'] < 1024
        assert 0 < state['received_bytes'] < 1024
    finally:
        lane.close()
    lane = SerialProcessLane(make_bytes, name='test-output-budget', max_message_bytes=1024)
    try:
        with pytest.raises(RuntimeError, match='output exceeds the byte budget'):
            lane.call(2048)
        assert lane.call(10) == bytes(10)
    finally:
        lane.close()


@pytest.mark.skipif(not hasattr(signal, 'SIGSTOP'), reason='POSIX owned-process suspension probe')
def test_large_send_has_physical_deadline_and_reaps_owned_child(monkeypatch):
    lane = SerialProcessLane(echo, name='test-send-deadline', timeout=10)
    try:
        assert lane.call('ready') == 'ready'
        # Cold process import is setup; the measured blocked send still has one second.
        monkeypatch.setattr(lane, '_timeout', 1.0)
        pid = lane.pid
        assert pid != os.getpid()
        os.kill(pid, signal.SIGSTOP)
        started = time.monotonic()
        # Much larger than the socket send buffer: this blocks in sendall,
        # before any response-wait deadline could have been reached.
        with pytest.raises(TimeoutError):
            lane.call(bytes(16 * 1024 * 1024))
        assert time.monotonic() - started < 8
        assert lane.snapshot()['timeouts'] == 1
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    finally:
        lane.close()
