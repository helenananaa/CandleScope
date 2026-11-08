"""Stable per-source epochs; execution generations may change on every resume."""
from __future__ import annotations

import hashlib
import re
from uuid import uuid4

from .errors import BacktestError


def _prefix(run_id):
    if not isinstance(run_id,str) or not 1<=len(run_id)<=128:
        raise BacktestError("CONTINUOUS_INPUT_INVALID","A bounded account owner is required")
    return "strategy-source:"+hashlib.sha256(run_id.encode("utf-8")).hexdigest()+":"


def new_source_owner(run_id):return _prefix(run_id)+uuid4().hex


def source_owner(run_id,definition):
    prefix=_prefix(run_id)
    legacy="strategy:"+run_id
    owner=definition.get("source_owner",legacy)
    if owner==legacy:return legacy
    if not isinstance(owner,str) or not owner.startswith(prefix) or not re.fullmatch(r"[0-9a-f]{32}",owner[len(prefix):]):
        raise BacktestError("CONTINUOUS_INPUT_INVALID","Source epoch does not belong to this account")
    return owner
