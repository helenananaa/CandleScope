"""Transfer an anonymous pipe writer to a spawned process (no log files)."""

import os
from multiprocessing import context, reduction


def _open_windows_handle(handle):
    import msvcrt
    return msvcrt.open_osfhandle(handle, os.O_WRONLY)


def _open_posix_handle(handle):
    return handle.detach()


class SpawnWriter:
    def __init__(self, fd):
        self.fd = fd

    def __reduce__(self):
        if os.name == "nt":
            import msvcrt
            # The duplicate belongs to the child even if startup is interrupted.
            handle = context.get_spawning_popen().duplicate_for_child(msvcrt.get_osfhandle(self.fd))
            return _open_windows_handle, (handle,)
        return _open_posix_handle, (reduction.DupFd(self.fd),)
