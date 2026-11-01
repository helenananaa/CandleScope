"""Private disposable worker. Author code is executed only in this process."""
from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time
import traceback

# -I deliberately excludes ambient PYTHONPATH and the current directory.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from author import analyze, columns, parameters, output_columns


class DiscardOutput:
    def write(self, value):
        return len(value)

    def flush(self):
        pass


def main():
    request_path, output_path = map(Path, sys.argv[1:])
    if sys.platform != "win32":
        import resource
        resource.setrlimit(resource.RLIMIT_FSIZE, (8 * 1024 * 1024, 8 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
        # The host may terminate the plugin while this fresh worker sleeps.
        # Its independent process group must not outlive that parent runtime.
        parent, worker = os.getppid(), os.getpid()
        get_parent, kill_group, sleep = os.getppid, os.killpg, time.sleep
        def watch_parent():
            while True:
                if get_parent() != parent:
                    kill_group(worker, signal.SIGKILL)
                    return
                sleep(.1)
        threading.Thread(target=watch_parent, daemon=True).start()
    request = json.loads(request_path.read_text(encoding="utf-8"))
    try:
        declaration = analyze(request["source"])
        bars = columns(request["bars"])
        params = parameters(declaration, request["params"])
        namespace = {"__name__": "__candlescope_indicator__", "__file__": "indicator.py"}
        with contextlib.redirect_stdout(DiscardOutput()), contextlib.redirect_stderr(DiscardOutput()):
            exec(compile(request["source"], "indicator.py", "exec"), namespace)
            result = namespace["compute"](bars, params)
            values = output_columns(declaration, result, len(request["bars"]))
        response = dict(ok=True, output={"lines": values})
    except BaseException as exc:
        frames = traceback.extract_tb(exc.__traceback__)
        line = next((frame.lineno for frame in reversed(frames) if frame.filename == "indicator.py"), None)
        response = dict(ok=False, error=dict(message=f"{type(exc).__name__}: {str(exc)[:1024]}", line=line))
    output_path.write_text(json.dumps(response, allow_nan=False), encoding="utf-8")


if __name__ == "__main__":
    main()
