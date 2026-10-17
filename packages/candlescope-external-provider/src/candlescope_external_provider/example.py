"""Small causal model for exercising the external connection, not investment advice."""

import hashlib
import json
import platform
from decimal import Decimal
from pathlib import Path
from typing import Any

from . import __version__


def manifest() -> dict[str, Any]:
    metadata = json.loads(Path(__file__).with_name("example_manifest.json").read_text(encoding="utf-8"))
    return {**metadata, "artifact_sha256": "sha256:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "runtime_lock": "python/" + platform.python_version() + ";candlescope-external-provider/" + __version__}


class RollingMeanModel:
    def prepare(self, context: dict[str, Any]) -> None:
        parameters = context.get("parameters") or {}
        if set(parameters) - {"quantity"}:
            raise ValueError("example only supports the quantity parameter")
        self.quantity = str(parameters.get("quantity", "0.001"))
        quantity = Decimal(self.quantity)
        if not quantity.is_finite() or not Decimal(0) < quantity <= Decimal(1):
            raise ValueError("example quantity must be in (0, 1]")
        self.closes: list[str] = []

    def warmup(self, observation: dict[str, Any]) -> None:
        self.closes = (self.closes + [str(observation["features"]["close"])])[-3:]

    def step(self, observation: dict[str, Any]) -> dict[str, Any]:
        close = Decimal(str(observation["features"]["close"]))
        mean = sum((Decimal(value) for value in self.closes), Decimal(0)) / len(self.closes)
        target = self.quantity if close > mean else "0"
        self.warmup(observation)
        return {"sequence": observation["sequence"], "kind": "TARGET_POSITION", "payload": {"targetExposure": target}}

    def on_execution_report(self, report: dict[str, Any]) -> None:
        pass  # Host alone owns order acceptance, risk decisions and fills.

    def snapshot(self) -> dict[str, Any]:
        return {"closes": list(self.closes), "quantity": self.quantity}

    def restore(self, state: dict[str, Any]) -> None:
        self.closes = list(state["closes"])
        self.quantity = str(state["quantity"])

    def close(self) -> None:
        pass
