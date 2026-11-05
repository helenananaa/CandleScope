"""Profile-exclusive ownership and finite disposable initialization inputs.

Only this controller's marked private directory can be collected. Financially
referenced and staged READY inputs remain pinned, including paused/failed runs.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile

from app.local_data.service import LocalDatasetService
from .errors import BacktestError

DATASET = re.compile(r"local-[0-9a-f]{32}\Z")


def reject_path_links(path):
    """A Windows junction is a reparse point but need not be a symlink."""
    try:metadata=Path(path).lstat()
    except FileNotFoundError:return
    if stat.S_ISLNK(metadata.st_mode) or getattr(metadata,"st_file_attributes",0)&0x400:
        raise BacktestError("CONTINUOUS_INPUT_OWNERSHIP","Owned path cannot be a symlink or reparse point")


class ProfileLease:
    def __init__(self,path):
        path=Path(path)
        reject_path_links(path)
        path.parent.mkdir(parents=True,exist_ok=True)
        self.handle=path.open("a+b")
        try:
            self.handle.seek(0,os.SEEK_END)
            if not self.handle.tell():self.handle.write(b"\0");self.handle.flush()
            self.handle.seek(0)
            if os.name=="nt":
                import msvcrt
                msvcrt.locking(self.handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BaseException as failure:
            self.handle.close()
            if isinstance(failure,OSError):
                raise BacktestError("CONTINUOUS_OWNER_BUSY","Another continuing execution owner holds this profile") from failure
            raise

    def close(self):
        # Do not unlink an advisory lock: that would allow two inode owners.
        if not self.handle.closed:self.handle.close()


class ContinuousInputs:
    def __init__(self,store,*,max_total_bytes=512*1024*1024,max_snapshot_bytes=128*1024*1024,min_free_bytes=64*1024*1024):
        if (any(type(value) is not int or value<1 for value in (max_total_bytes,max_snapshot_bytes,min_free_bytes))
                or max_snapshot_bytes>max_total_bytes):raise ValueError("Invalid continuing input budgets")
        self.store=store
        self.root=store.path.parent/"continuous-strategy-inputs"
        self.max_total_bytes,self.max_snapshot_bytes,self.min_free_bytes=max_total_bytes,max_snapshot_bytes,min_free_bytes
        self._own_directory()
        self._size(self.root)
        self.datasets=LocalDatasetService(self.root/"datasets")

    def _own_directory(self):
        reject_path_links(self.root)
        marker=self.root/"owner.json"
        reject_path_links(marker)
        expected={"schema":"candlescope.continuous-private-inputs/1","database":str(self.store.path.resolve())}
        if self.root.exists():
            if not marker.is_file():
                if any(self.root.iterdir()):raise BacktestError("CONTINUOUS_INPUT_OWNERSHIP","Refuse to adopt unmarked existing input data")
            else:
                try:actual=json.loads(marker.read_text())
                except (OSError,ValueError) as error:raise BacktestError("CONTINUOUS_INPUT_OWNERSHIP","Private input ownership receipt is unavailable") from error
                if actual!=expected:raise BacktestError("CONTINUOUS_INPUT_OWNERSHIP","Private inputs belong to another profile")
                return
        self.root.mkdir(parents=True,exist_ok=True,mode=0o700)
        # A crash before replace leaves the private root empty, so ownership
        # can be established on restart without adopting an unmarked tree.
        fd,name=tempfile.mkstemp(prefix=".continuous-input-owner-",dir=self.root.parent)
        temporary=Path(name)
        try:
            with os.fdopen(fd,"w",encoding="utf-8") as output:
                json.dump(expected,output,sort_keys=True);output.flush();os.fsync(output.fileno())
            temporary.replace(marker)
        finally:temporary.unlink(missing_ok=True)

    def _size(self,path):
        reject_path_links(path)
        if not path.exists():return 0
        if path.is_file():return path.stat().st_size
        return sum(self._size(child) for child in path.iterdir())

    def _references(self):
        keep=set()
        for row in self.store.list_summaries():
            initial=self.store.describe(row["id"])["definition"].get("initial_snapshot")
            if initial:keep.add(initial["dataset_id"])
        for row in self.store.creations.list_pending():
            if row["phase"]=="CANCELLED":continue
            initial=self.store.creations.describe(row["request_key"])["input"]
            if initial:keep.add(initial["descriptor"]["dataset_id"])
        return keep

    def collect(self):
        """Called only on the exclusive preparation worker with no other copy."""
        self._own_directory()
        self._size(self.root)  # Refuse every symlink before removing anything.
        keep=self._references();removed=[]
        root=self.datasets.root
        if root.exists():
            for child in root.iterdir():
                if DATASET.fullmatch(child.name) and child.name not in keep:
                    shutil.rmtree(child);removed.append(child.name)
                elif child.name==".staging":
                    for stale in child.iterdir():
                        if not stale.is_dir():raise BacktestError("CONTINUOUS_INPUT_OWNERSHIP","Unknown initialization staging entry")
                        shutil.rmtree(stale);removed.append(".staging/"+stale.name)
        return removed

    def payload_budget(self):
        self.collect()
        remaining=self.max_total_bytes-self._size(self.root)
        available=min(self.max_snapshot_bytes,remaining)
        if available<4096 or shutil.disk_usage(self.root).free<available*4+self.min_free_bytes:
            raise BacktestError("BUDGET_EXCEEDED","Continuing initialization disk budget is exhausted")
        # LocalDataset stores both canonical text and SQLite. Bound source
        # payload before it materializes, then check actual published bytes.
        return max(1,available//4)

    def check_published(self,dataset_id):
        if not DATASET.fullmatch(dataset_id):raise BacktestError("CONTINUOUS_INPUT_OWNERSHIP","Unknown private input identity")
        if (self._size(self.datasets.root/dataset_id)>self.max_snapshot_bytes
                or self._size(self.root)>self.max_total_bytes):
            self.collect()  # Not READY/financially referenced yet; only ours.
            raise BacktestError("BUDGET_EXCEEDED","Published initialization exceeds the disk budget")
