"""One owned process for a serial, bounded caller; IPC runs off the loop."""
from __future__ import annotations

import multiprocessing


def _serve(connection, dispatch):
    try:
        while True:
            request = connection.recv()
            if request is None:
                return
            try:
                value = dispatch(*request)
            except Exception as error:
                connection.send((False, error))
            else:
                connection.send((True, value))
    except (EOFError, BrokenPipeError):
        return
    finally:
        connection.close()


class SerialProcessLane:
    """Own exactly one child, with an explicit deadline and physical cleanup.

    A dedicated caller thread serializes access. It retains its admission slot
    until this call returns, including termination after a timeout. The child
    only receives trusted installed dispatch functions and detached arguments.
    """

    def __init__(self, dispatch, *, name: str, timeout: float = 30.0):
        context = multiprocessing.get_context('spawn')
        self._connection, child = context.Pipe()
        self._process = context.Process(target=_serve, args=(child, dispatch), name=name, daemon=True)
        self._closed = False
        self._timeout = max(.1, float(timeout))
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

    def call(self, *request):
        if not self.alive:
            self.close()
            raise RuntimeError('Owned compute process exited before accepting the command')
        try:
            self._connection.send(request)
            if not self._connection.poll(self._timeout):
                self.close(force=True)
                raise TimeoutError('Owned compute process exceeded its physical deadline')
            ok, value = self._connection.recv()
        except TimeoutError:
            raise
        except (EOFError, BrokenPipeError, OSError) as error:
            self.close(force=True)
            raise RuntimeError('Owned compute process exited during the command') from error
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
                        self._connection.send(None)
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
