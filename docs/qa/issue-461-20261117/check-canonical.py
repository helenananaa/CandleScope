"""Independent SQL/math oracle for closed dense minute-derived native targets.

Run after the owned native process has exited. No network, writes, production
query/reducer/cache code, or assumption that missing inputs prove completeness.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sqlite3

parser = argparse.ArgumentParser()
parser.add_argument('database', type=Path)
parser.add_argument('output', type=Path)
parser.add_argument('--closed-before-ms', type=int, required=True)
args = parser.parse_args()
conn = sqlite3.connect(args.database.resolve().as_uri()+'?mode=ro', uri=True)
conn.row_factory = sqlite3.Row
# These are the retained source-quality contract's trusted-final labels. Unknown
# labels are explicitly skipped, never promoted by the numerical oracle.
trusted = {'source_snapshot_verified', 'backfill', 'backfill_rest_verified',
           'backfill_archive_verified', 'backfill_archive_confirmed',
           'data_manager_exchange_closed', 'data_manager_amended',
           'repair_binance_rest_verified'}
identity = "exchange='binance' AND market_type='futures' AND symbol='BTCUSDT' " \
           "AND provider_id='binance' AND venue='binance' AND asset_class='crypto' " \
           "AND series_variant='native' AND price_adjustment='raw' " \
           "AND session_variant='continuous' AND volume_semantics='base_asset'"
additive = ['volume', 'quote_volume', 'trades', 'taker_buy_base', 'taker_buy_quote']
result = {'scope': 'closed dense 1m-derived persisted targets only; no chart, mixed-grid or lifecycle qualification',
          'closed_before_ms': args.closed_before_ms, 'per_interval': [], 'mismatches': []}
for minutes in [89, 97, 101]:
    duration = minutes*60_000
    targets = conn.execute('SELECT * FROM klines WHERE '+identity+' AND interval=? ORDER BY open_time',
                           (str(minutes)+'m',)).fetchall()
    checked = []
    skipped = []
    digest = hashlib.sha256()
    for target in targets:
        start = target['open_time']
        rows = conn.execute('SELECT * FROM klines WHERE '+identity+
                            " AND interval='1m' AND open_time>=? AND open_time<? ORDER BY open_time",
                            (start, start+duration)).fetchall()
        reason = None
        if start % duration or target['close_time'] != start+duration-1:
            reason = 'invalid_target_grid'
        elif target['close_time'] >= args.closed_before_ms:
            reason = 'not_closed_at_observation_stop'
        elif target['source'] != 'backfill_aggregated':
            reason = 'unqualified_target_source'
        elif len(rows) != minutes or any(r['open_time'] != start+i*60_000 or
                r['close_time'] != start+(i+1)*60_000-1 for i, r in enumerate(rows)):
            reason = 'missing_or_invalid_minute_inputs'
        elif any(r['source'] not in trusted for r in rows):
            reason = 'untrusted_minute_inputs'
        if reason:
            skipped.append({'open_time': start, 'reason': reason, 'input_rows': len(rows)})
            continue
        expected = {'open': rows[0]['open'], 'close': rows[-1]['close'],
                    'high': max(r['high'] for r in rows), 'low': min(r['low'] for r in rows)}
        expected.update({field: None if any(r[field] is None for r in rows)
                         else math.fsum(r[field] for r in rows) for field in additive})
        for field, value in expected.items():
            actual = target[field]
            equal = actual == value if actual is None or value is None else math.isclose(
                actual, value, rel_tol=1e-12, abs_tol=1e-9)
            if not equal:
                result['mismatches'].append({'interval': str(minutes)+'m', 'open_time': start,
                                             'field': field, 'expected': value, 'actual': actual})
        digest.update(json.dumps({'target':dict(target), 'inputs':[dict(r) for r in rows]},
                                 sort_keys=True).encode())
        checked.append(start)
    result['per_interval'].append({'interval': str(minutes)+'m', 'stored':len(targets),
        'checked_closed_targets':len(checked), 'checked_open_times':checked,
        'skipped':skipped, 'canonical_target_sha256':digest.hexdigest()})
result['passed'] = not result['mismatches'] and all(
    item['checked_closed_targets'] > 0 for item in result['per_interval'])
args.output.write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps(result))
raise SystemExit(0 if result['passed'] else 1)
