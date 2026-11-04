"""Fresh process per batch; this is an isolation boundary, not a security sandbox."""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile

from .author import analyze, AuthorError, columns, parameters, output_columns

MAX_RESULT_BYTES = 4 * 1024 * 1024
WORKER = Path(__file__).with_name("worker.py")


def execute(source, bars, values, *, timeout=10):
    declaration = analyze(source)
    columns(bars)
    params = dict(parameters(declaration, values))
    if len(bars) > declaration.window:
        raise AuthorError("Input exceeds declared computation window; host must select the declared window explicitly")
    with tempfile.TemporaryDirectory(prefix="candlescope-python-indicator-") as directory:
        root = Path(directory)
        request = root / "request.json"
        result = root / "result.json"
        request.write_text(json.dumps(dict(source=source, bars=bars, params=params), allow_nan=False), encoding="utf-8")
        with (root / "stdout.log").open("wb") as stdout, (root / "stderr.log").open("wb") as stderr:
            process = subprocess.Popen([sys.executable, "-I", "-B", str(WORKER), str(request), str(result)],
                                       cwd=root, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                       start_new_session=os.name == "posix")
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                    process.kill()
                process.wait()
                raise AuthorError("Python batch exceeded execution deadline") from exc
            finally:
                # A successful author function may have spawned descendants.
                # They must not become hidden state of the next batch.
                if os.name == "posix":
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
        if process.returncode != 0:
            raise AuthorError(f"Python worker exited with code {process.returncode}")
        if not result.is_file() or result.stat().st_size > MAX_RESULT_BYTES:
            raise AuthorError("Python worker returned missing or oversized output")
        try:
            response = json.loads(result.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise AuthorError("Python worker returned malformed output") from exc
        if not isinstance(response, dict) or type(response.get("ok")) is not bool:
            raise AuthorError("Python worker returned an invalid response")
        if not response["ok"]:
            error = response.get("error", {})
            if not isinstance(error, dict):
                raise AuthorError("Python worker returned invalid diagnostics")
            raise AuthorError(str(error.get("message", "Execution failed"))[:2048],
                              line=error.get("line"))
        # Repeat value validation outside the author-controlled interpreter.
        return declaration, output_columns(declaration, response.get("output"), len(bars))
