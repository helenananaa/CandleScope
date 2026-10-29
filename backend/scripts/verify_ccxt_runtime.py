"""Fail packaging if the installed CCXT lacks the locked public-data contract."""
from __future__ import annotations

import argparse
import importlib.resources
import json
from pathlib import Path


def verify(lock_path: Path) -> dict:
    import ccxt

    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    build = json.loads(importlib.resources.files("ccxt").joinpath("candlescope_build.json").read_text())
    if ccxt.__version__ != lock["upstream_version"] or build["source_commit"] != lock["source_commit"]:
        raise RuntimeError("Installed CCXT differs from the release lock")
    contracts = {}
    for venue in ("binance", "binanceusdm", "okx"):
        client = getattr(ccxt, venue)()
        contract = client.candlescope_kline_contract()
        if contract["upstream"] != lock["upstream_version"] or contract["schema"] not in lock["schemas"]:
            raise RuntimeError(f"Incompatible CCXT contract: {venue}")
        if not callable(client.fetch_candlescope_klines):
            raise RuntimeError(f"Missing fork history API: {venue}")
        contracts[venue] = contract
    return {"source_commit": build["source_commit"], "wheel_sha256": lock["wheel_sha256"],
            "contracts": contracts}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=Path(__file__).resolve().parents[1] / "ccxt-fork.lock.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    receipt = json.dumps(verify(args.lock), indent=2) + "\n"
    if args.output:
        args.output.write_text(receipt, encoding="utf-8")
    else:
        print(receipt)
