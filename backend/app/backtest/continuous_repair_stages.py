"""Finite disposable financial stores, owned by the profile execution lease."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from .continuous_store import ContinuousStrategyStore, fail

EPOCH = re.compile(r"[0-9a-f]{32}\Z")


def linked(path):
    if path.is_symlink(): return True
    try: return bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)
    except FileNotFoundError: return False


class RepairStages:
    def __init__(self, store, *, max_total_bytes=512*1024*1024,
                 max_stage_bytes=256*1024*1024, min_free_bytes=64*1024*1024):
        if (any(type(value) is not int or value < 1 for value in
                (max_total_bytes, max_stage_bytes, min_free_bytes)) or max_stage_bytes > max_total_bytes):
            raise ValueError("Invalid history repair disk budgets")
        self.store = store
        self.root = store.path.parent / "continuous-strategy-repairs"
        self.max_total_bytes, self.max_stage_bytes, self.min_free_bytes = max_total_bytes, max_stage_bytes, min_free_bytes
        self.owner = {"schema": "candlescope.continuous-repair-stages/1", "database": str(store.path.resolve())}
        self._own(self.root, self.owner)
        self._inventory()

    @staticmethod
    def _own(path, expected):
        marker = path / "owner.json"
        if linked(path) or linked(marker):
            raise fail("CONTINUOUS_INPUT_OWNERSHIP", "Repair ownership cannot cross a symlink")
        if path.exists():
            if not path.is_dir():
                raise fail("CONTINUOUS_INPUT_OWNERSHIP", "Repair staging must be a private directory")
            if marker.exists():
                try: actual = json.loads(marker.read_text())
                except (OSError, ValueError) as failure:
                    raise fail("CONTINUOUS_INPUT_OWNERSHIP", "Repair ownership receipt is unavailable") from failure
                if actual != expected:
                    raise fail("CONTINUOUS_INPUT_OWNERSHIP", "Repair staging belongs to another owner")
                return
            if any(path.iterdir()):
                raise fail("CONTINUOUS_INPUT_OWNERSHIP", "Refuse to adopt unmarked repair data")
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, name = tempfile.mkstemp(prefix=".repair-owner-", dir=path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump(expected, output, sort_keys=True)
                output.flush(); os.fsync(output.fileno())
            temporary.replace(marker)
        finally: temporary.unlink(missing_ok=True)

    @staticmethod
    def _size(path):
        if linked(path):
            raise fail("CONTINUOUS_INPUT_OWNERSHIP", "Repair staging contains a foreign symlink")
        if path.is_file(): return path.stat().st_size
        if path.is_dir(): return sum(RepairStages._size(child) for child in path.iterdir())
        raise fail("CONTINUOUS_INPUT_OWNERSHIP", "Repair staging contains an unknown filesystem entry")

    def _inventory(self):
        self._own(self.root, self.owner)
        total = 0
        for child in self.root.iterdir():
            if child.name == "owner.json": continue
            if not EPOCH.fullmatch(child.name) or not child.is_dir() or linked(child):
                raise fail("CONTINUOUS_INPUT_OWNERSHIP", "Unknown repair staging entry is retained")
            record = self.store.epochs.describe(child.name)
            self._own(child, self._marker(record))
            if any(item.name not in {"owner.json", "account.sqlite3", "account.sqlite3-wal", "account.sqlite3-shm"}
                   for item in child.iterdir()):
                raise fail("CONTINUOUS_INPUT_OWNERSHIP", "Unknown private repair file is retained")
            total += self._size(child)
        return total

    def _marker(self, record):
        return {**self.owner, "epoch": record["id"], "run_id": record["run_id"], "source_owner": record["source_owner"]}

    def check(self, record, *, reserve=False):
        total = self._inventory()
        path = self.root / record["id"]
        size = self._size(path) if path.exists() else 0
        if (size > self.max_stage_bytes or total > self.max_total_bytes
                or (reserve and total - size + self.max_stage_bytes > self.max_total_bytes)
                or shutil.disk_usage(self.root).free < self.min_free_bytes + (self.max_stage_bytes if reserve else 0)):
            raise fail("BUDGET_EXCEEDED", "History repair staging disk budget is exhausted; saved account is retained")

    def open(self, record):
        if not EPOCH.fullmatch(record["id"]):
            raise fail("CONTINUOUS_INPUT_OWNERSHIP", "Unknown repair staging identity")
        self.check(record, reserve=True)
        path = self.root / record["id"]
        self._own(path, self._marker(record))
        for child in path.iterdir():
            if child.name not in {"owner.json", "account.sqlite3", "account.sqlite3-wal", "account.sqlite3-shm"}:
                raise fail("CONTINUOUS_INPUT_OWNERSHIP", "Unknown private repair file is retained")
        staged = ContinuousStrategyStore(path / "account.sqlite3", max_runs=1,
            max_total_checkpoint_bytes=min(self.max_stage_bytes, 128*1024*1024))
        try: self.check(record)
        except BaseException:
            staged.close()
            raise
        return staged

    def remove(self, record):
        """Caller physically drains the worker before terminal cleanup."""
        current = self.store.epochs.describe(record["id"])
        if current["phase"] not in {"COMMITTED", "FAILED", "CANCELLED"}:
            raise fail("CONTINUOUS_NOT_READY", "Pending repair must retain its private recovery store")
        self._inventory()
        path = self.root / current["id"]
        if path.exists():
            self._own(path, self._marker(current))
            # This path is never adopted by a financial/source row. Publication
            # copies the complete checkpoint/projection into the primary store.
            shutil.rmtree(path)
