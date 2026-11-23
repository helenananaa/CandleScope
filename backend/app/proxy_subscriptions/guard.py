"""Own the core until it exits or the backend's private stdin pipe closes."""
import subprocess
import sys
import tempfile
import threading


def main():
    config = sys.stdin.buffer.readline()
    if not config:
        return 1
    with tempfile.TemporaryDirectory(prefix="candlescope-proxy-") as directory:
        with subprocess.Popen([sys.argv[1], "-d", directory, "-f", "-"],
                              stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) as child:
            try:
                with child.stdin:
                    child.stdin.write(config)
                del config
                def watch_backend():
                    sys.stdin.buffer.read(1)
                    if child.poll() is None:
                        child.terminate()
                        try:
                            child.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            child.kill()

                threading.Thread(target=watch_backend, daemon=True).start()
                status = child.wait()
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait()
            return status


if __name__ == "__main__":
    # A daemon blocked on a buffered stdin read can deadlock interpreter shutdown.
    import os
    os._exit(main())
