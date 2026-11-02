"""Content identity for immutable-dataset builtin results, independent of views."""
from __future__ import annotations

from functools import lru_cache
import hashlib
import json
from pathlib import Path
import platform
import sys

from app.indicator import registry
from app.indicator.script_identity import object_source_hash
from .indicator_compute import _normalize_params

CACHE_SCHEMA = 'candlescope.local-builtin-result/2'


@lru_cache(maxsize=1)
def implementation_revision() -> str:
    """Fingerprint installed code and arithmetic runtime once per process.

    Include shared formulas, serialization and input/resampling semantics, not
    just an indicator class file. Missing source disables reuse, never grants
    an unknown implementation the identity of a previous build.
    """
    root = Path(__file__).resolve().parents[1]
    paths = set((root / 'indicator').rglob('*.py'))
    paths.update((root / 'local_data').glob('*.py'))
    paths.update(root / name for name in (
        'data_engine/data_manager/models.py', 'data_engine/interval_policy.py',
        'data_engine/bar_basis.py', 'data_engine/calendar_basis.py',
        'data_engine/basis_rules/calendar-v1.json',
    ))
    digest = hashlib.sha256()
    digest.update(f'{sys.version}:{platform.system()}:{platform.machine()}'.encode())
    try:
        for path in sorted(paths):
            digest.update(str(path.relative_to(root)).encode())
            digest.update(b'\0')
            digest.update(path.read_bytes())
            digest.update(b'\0')
    except OSError:
        return ''
    return digest.hexdigest()


def result_key(*, manifest: dict, interval: str, requests: list[dict]) -> str | None:
    revision = implementation_revision()
    if not revision:
        return None
    computations = []
    try:
        for item in requests:
            name = str(item['name']).upper()
            params = _normalize_params(name, dict(item.get('params') or {}),
                                       volume_available=bool(manifest.get('volume_available')))
            code_hash = object_source_hash(registry.get(name), length=64)
            if not code_hash:
                return None
            computations.append({'name': name, 'params': params, 'code': code_hash})
    except (TypeError, ValueError):
        # Let the existing compute contract return its per-item diagnostics.
        return None
    identity = {
        'schema': CACHE_SCHEMA, 'implementation': revision,
        'dataset_id': manifest['dataset_id'], 'data_epoch': manifest['data_epoch'],
        'sqlite_sha256': manifest.get('sqlite_sha256'),
        'source': manifest.get('source'), 'symbol': manifest['symbol'],
        'source_interval': manifest['interval'], 'bar_basis': manifest.get('bar_basis'),
        'interval': interval, 'volume_available': manifest.get('volume_available'),
        'input_policy': 'entire_immutable_revision_v1', 'computations': computations,
    }
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def bind_results(payload: dict, requests: list[dict]) -> dict | None:
    """Validate the successful envelope and bind request-only delivery IDs."""
    results = payload.get('results')
    if payload.get('ok') is not True or not isinstance(results, list) or len(results) != len(requests):
        return None
    if any(not isinstance(item, dict) or not isinstance(item.get('payload'), dict)
           or item['payload'].get('ok') is not True for item in results):
        return None
    return {**payload, 'results': [
        {'jobKey': request['jobKey'], 'clientId': request['clientId'], 'payload': item['payload']}
        for item, request in zip(results, requests)
    ]}
