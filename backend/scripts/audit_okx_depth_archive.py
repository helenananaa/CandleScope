"""Audit public OKX archives without inventing exchange continuity or full depth.

Reads archive members directly; never extracts files or upgrades them to BOOK_DEPTH.
Example: python backend/scripts/audit_okx_depth_archive.py --directory output/native-v8
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import tarfile
import zipfile


def identity(path: Path) -> dict:
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'file': path.name, 'bytes': path.stat().st_size, 'sha256': digest}


def utc(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def audit(directory: Path) -> dict:
    book_path = directory / 'BTC-USDT-L2orderbook-5000lv-2026-06-01.tar.gz'
    actions, intervals, fields = Counter(), Counter(), Counter()
    first = last = previous = None
    snapshots = []
    backwards = 0
    with tarfile.open(book_path, 'r:gz') as archive:
        members = [m for m in archive if m.isfile()]
        if len(members) != 1:
            raise ValueError('Expected one orderbook data member')
        with archive.extractfile(members[0]) as stream:
            for raw in stream:
                event = json.loads(raw)
                if event['instId'] != 'BTC-USDT':
                    raise ValueError('Unexpected instrument')
                ts = int(event['ts'])
                first = ts if first is None else min(first, ts)
                last = ts if last is None else max(last, ts)
                if previous is not None:
                    intervals[ts - previous] += 1
                    backwards += ts < previous
                previous = ts
                fields.update(event.keys())
                actions[event['action']] += 1
                if event['action'] == 'snapshot':
                    snapshots.append({'time_ms': ts, 'bids': len(event['bids']), 'asks': len(event['asks'])})
    if first is None or last is None:
        raise ValueError('Empty book archive')
    trades = []
    for path in sorted(directory.glob('BTC-USDT-trades-2026-06-0[12].zip')):
        sides, count, overlapping, start, end = Counter(), 0, 0, None, None
        regressions = 0
        previous_ts = None
        with zipfile.ZipFile(path) as archive:
            if len(archive.namelist()) != 1:
                raise ValueError('Expected one trade CSV member')
            with archive.open(archive.namelist()[0]) as stream:
                for row in csv.DictReader(io.TextIOWrapper(stream, encoding='utf-8-sig')):
                    if row['instrument_name'] != 'BTC-USDT':
                        raise ValueError('Unexpected trade instrument')
                    ts = int(row['created_time'])
                    start = ts if start is None else min(start, ts)
                    end = ts if end is None else max(end, ts)
                    regressions += previous_ts is not None and ts < previous_ts
                    previous_ts = ts
                    sides[row['side']] += 1
                    count += 1
                    overlapping += first <= ts <= last
        trades.append({**identity(path), 'rows': count, 'sides': dict(sides),
                       'first_utc': utc(start), 'last_utc': utc(end),
                       'timestamp_regressions': regressions, 'rows_in_book_time_range': overlapping})
    links = {}
    for path in directory.glob('okx-*-links.json'):
        links[path.name] = json.loads(path.read_text(encoding='utf-8-sig'))
    links['okx-links.json'] = json.loads((directory / 'okx-links.json').read_text(encoding='utf-8-sig'))
    return {'schema': 'candlescope.okx-archive-audit/1', 'source': 'https://www.okx.com/zh-hans/historical-data',
            'audited_at_utc': datetime.now(timezone.utc).isoformat(),
            'transport': 'Official public HTTPS; curl --resolve after local DNS failure; TLS verification enabled; no credentials',
            'orderbook': {**identity(book_path), 'actions': dict(actions), 'field_counts': dict(fields),
                          'first_utc': utc(first), 'last_utc': utc(last), 'snapshots': snapshots,
                          'interval_ms_counts': dict(sorted(intervals.items())), 'timestamp_regressions': backwards},
            'trades': trades, 'official_download_responses': links,
            'book_depth_admissible': False,
            'reasons': ['5000 levels per side are a bounded view, not a declaration of complete depth',
                        'Archive omits exchange seqId/prevSeqId; lossless event continuity cannot be established',
                        'Timestamp cadence does not establish all intervening book events or trade/book ordering',
                        'Aggregated L2 has no order-level priority; exact FIFO cannot be validated'],
            'scope': 'Archive integrity and schema audit only; no queue-model real-data qualification; no synthetic depth_complete or exchange sequence added'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = audit(args.directory)
    target = args.output or args.directory / 'okx-archive-audit.json'
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'output': str(target), 'actions': result['orderbook']['actions'],
                      'trades': sum(t['rows'] for t in result['trades']), 'book_depth_admissible': False}))
