"""Desktop-owned Uvicorn process with portable graceful shutdown over stdin.

The inherited pipe is private to the parent. EOF also shuts down if the host
crashes; no network control endpoint or persistent credential is introduced.
"""
from __future__ import annotations

import argparse
import sys
import threading

import uvicorn


def serve(host: str, port: int) -> None:
    server = uvicorn.Server(uvicorn.Config("app.main:app", host=host, port=port))

    def watch_parent() -> None:
        for line in sys.stdin:
            if line.strip() == "shutdown":
                break
        server.should_exit = True

    threading.Thread(target=watch_parent, name="desktop-parent-pipe", daemon=True).start()
    server.run()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    serve(args.host, args.port)
