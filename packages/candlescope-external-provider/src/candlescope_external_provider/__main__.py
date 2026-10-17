import argparse
import signal
import sys
import threading
from pathlib import Path

from .client import ExternalClient
from .errors import ExternalProviderError
from .example import RollingMeanModel, manifest
from .wire import encode


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the independent CandleScope rolling-mean model")
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--manifest", action="store_true", help="print the data-only frozen model manifest")
    choice.add_argument("--connection", type=Path, help="explicit private Host connection file")
    args = parser.parse_args()
    if args.manifest:
        print(encode(manifest()))
        return 0
    stopped = threading.Event()
    for number in (signal.SIGINT, signal.SIGTERM):
        signal.signal(number, lambda *_args: stopped.set())
    try:
        ExternalClient(args.connection, manifest(), RollingMeanModel).run(stopped)
        return 0
    except ExternalProviderError as exc:
        print(exc.code + ": external connection stopped", file=sys.stderr)
        return 1
    except OSError:
        print("CONNECTION_FILE_UNAVAILABLE: explicit private connection file could not be read", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
