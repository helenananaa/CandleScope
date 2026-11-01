"""One owned process for a serial, bounded caller; IPC runs off the loop."""
from __future__ import annotations

import multiprocessing
import pickle
import socket
import struct
import time


class ProcessMessageTooLarge(ValueError):
    """Rejected before sending any part of a request to the owned process."""


def _receive(connection, maximum, deadline=None):
    def exact(size):
        chunks = bytearray(size)
        view = memoryview(chunks)
        offset = 0
        while offset < size:
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('Owned compute receive deadline expired')
                connection.settimeout(remaining)
            count = connection.recv_into(view[offset:])
            if not count:
                raise EOFError('Owned compute channel closed')
            offset += count
        return chunks
    size, = struct.unpack('!Q', exact(8))
    if size > maximum:
        raise ValueError('Owned compute message exceeds the byte budget')
    payload = exact(size)
    return pickle.loads(payload), size


def _send(connection, value, maximum, deadline=None):
    payload = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
    if len(payload) > maximum:
        raise ProcessMessageTooLarge('Owned compute message exceeds the byte budget')
    if deadline is not None:
        if time.monotonic() >= deadline:
            raise TimeoutError('Owned compute serialization exceeded its physical deadline')
        connection.settimeout(deadline - time.monotonic())
    connection.sendall(struct.pack('!Q', len(payload)))
    if deadline is not None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('Owned compute send deadline expired')
        connection.settimeout(remaining)
    connection.sendall(payload)
    return len(payload)


def _serve(connection, dispatch, maximum):
    try:
        while True:
            request, _ = _receive(connection, maximum)
            if request is None:
                return
            try:
                value = dispatch(*request)
            except Exception as error:
                _send(connection, (False, error), maximum)
            else:
                try:
                    _send(connection, (True, value), maximum)
                except ValueError:
                    # The computation may already have changed worker state.
                    # The realtime owner treats this as terminal and resyncs.
                    _send(connection, (False, RuntimeError('Owned compute output exceeds the byte budget')), maximum)
    except (EOFError, BrokenPipeError, ConnectionResetError):
        return
    finally:
        connection.close()


class SerialProcessLane:
    """Own exactly one child, with an explicit deadline and physical cleanup.

    A dedicated caller thread serializes access. It retains its admission slot
    until this call returns, including termination after a timeout. The child
    only receives trusted installed dispatch functions and detached arguments.
    """

    def __init__(self, dispatch, *, name: str, timeout: float = 30.0,
                 max_message_bytes: int = 64 * 1024 * 1024):
        context = multiprocessing.get_context('spawn')
        if max_message_bytes < 1024:
            raise ValueError('Compute message byte budget is too small')
        self._connection, child = socket.socketpair()
        self._maximum = max_message_bytes
        self._process = context.Process(target=_serve, args=(child, dispatch, max_message_bytes), name=name, daemon=True)
        self._closed = False
        self._timeout = max(.1, float(timeout))
        self._metrics = {'sent_bytes': 0, 'received_bytes': 0, 'calls': 0, 'timeouts': 0,
                         'max_message_bytes': max_message_bytes, 'last_roundtrip_ms': 0.0}
        try:
            self._process.start()
        except BaseException:
            self._connection.close()
            raise
        finally:
            child.close()

    @property
    def alive(self):
        return not self._closed and self._process.is_alive()

    @property
    def pid(self):
        return None if self._closed else self._process.pid

    def snapshot(self):
        return dict(self._metrics)

    def call(self, *request):
        if not self.alive:
            self.close()
            raise RuntimeError('Owned compute process exited before accepting the command')
        started = time.monotonic()
        deadline = started + self._timeout
        try:
            self._metrics['sent_bytes'] += _send(self._connection, request, self._maximum, deadline)
            (ok, value), received = _receive(self._connection, self._maximum, deadline)
            self._metrics['received_bytes'] += received
            if time.monotonic() >= deadline:
                raise TimeoutError('Owned compute result exceeded its physical deadline')
        except TimeoutError as error:
            self._metrics['timeouts'] += 1
            self.close(force=True)
            raise TimeoutError('Owned compute process exceeded its physical deadline') from error
        except (EOFError, BrokenPipeError, OSError) as error:
            self.close(force=True)
            raise RuntimeError('Owned compute process exited during the command') from error
        finally:
            self._metrics['calls'] += 1
            self._metrics['last_roundtrip_ms'] = (time.monotonic() - started) * 1000
        if not ok:
            raise value
        return value

    def close(self, *, force: bool = False):
        if self._closed:
            return
        process = self._process
        try:
            if process.is_alive():
                if force:
                    process.terminate()
                else:
                    try:
                        _send(self._connection, None, self._maximum, time.monotonic() + .1)
                    except (EOFError, BrokenPipeError, OSError):
                        pass
                process.join(timeout=2)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=2)
                if process.is_alive():
                    process.kill()
            process.join()
        finally:
            self._connection.close()
            process.close()
            self._closed = True
