"""Download official OKX archives and create paired bars / BOOK_SAMPLED inputs.

No archive extraction, synthetic exchange sequences, or complete-depth claims.
UTC minute boundaries are explicit. Trade ZIP dates use UTC+8, so two files are
requested for each UTC book day. Run with --help for reproducible usage.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import csv
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import zipfile

MODEL = 'SAMPLED_L2_VISIBLE_TAKER_ONLY_V1'


def file_hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def download_day(directory, day, resolves=()):
    """Public endpoints only. curl keeps normal TLS certificate verification."""
    directory.mkdir(parents=True, exist_ok=True)
    curl = ['curl', '--fail', '--silent', '--show-error', '--location',
            '--connect-timeout', '15', '--max-time', '300', '--max-filesize', '536870912',
            '--retry', '3', '--retry-delay', '2', '--retry-max-time', '30']
    for resolve in resolves:
        curl += ['--resolve', resolve]
    for module, date in [('5', day), ('1', day), ('1', day + timedelta(days=1))]:
        expected = (f'BTC-USDT-L2orderbook-5000lv-{date:%Y-%m-%d}.tar.gz' if module == '5'
                    else f'BTC-USDT-trades-{date:%Y-%m-%d}.zip')
        if (directory / expected).is_file():
            continue  # Reuse archives; conversion below checks contents and records SHA256.
        stamp = str(int(date.timestamp() * 1000))
        request = {'module': module, 'instType': 'SPOT', 'instQueryParam': {'instIdList': ['BTC-USDT']},
                   'dateQuery': {'dateAggrType': 'daily', 'begin': stamp, 'end': stamp}}
        stem = f'okx-{module}-{date:%Y%m%d}'
        body, response = directory / f'{stem}-request.json', directory / f'{stem}-links.json'
        body.write_text(json.dumps(request), encoding='utf-8')
        response_part = response.with_suffix('.part')
        subprocess.run([*curl, '-H', 'Content-Type: application/json', '--data-binary', f'@{body}',
                        '--output', str(response_part), 'https://www.okx.com/priapi/v5/broker/public/trade-data/download-link'], check=True)
        result = json.loads(response_part.read_text(encoding='utf-8-sig'))
        if result.get('code') != '0':
            raise ValueError(f'OKX refused public download: {result.get("code")} {result.get("msg")}')
        response_part.replace(response)
        entries = [entry for detail in result['data']['details'] for entry in detail['groupDetails']]
        if len(entries) != 1:
            raise ValueError('Expected one archive per instrument/day')
        entry = entries[0]
        name, url = entry['filename'], entry['url']
        if Path(name).name != name or not url.startswith('https://static.okx.com/'):
            raise ValueError('Unexpected download destination')
        target = directory / name
        # Refreshing metadata never overwrites an already saved archive.
        if not target.exists():
            partial = target.with_name(target.name + '.part')
            subprocess.run([*curl, '--output', str(partial), url], check=True)
            partial.replace(target)


def book_records(path):
    with tarfile.open(path, 'r:gz') as archive:
        files = [m for m in archive if m.isfile()]
        if len(files) != 1:
            raise ValueError('Expected one orderbook member')
        with archive.extractfile(files[0]) as stream:
            for raw in stream:
                yield json.loads(raw)


def trade_records(paths):
    for path in paths:
        with zipfile.ZipFile(path) as archive:
            if len(archive.namelist()) != 1:
                raise ValueError('Expected one trade member')
            with archive.open(archive.namelist()[0]) as stream:
                yield from csv.DictReader(io.TextIOWrapper(stream, encoding='utf-8-sig'))


def convert(book_path, trade_paths, start_ms, end_ms):
    if start_ms % 60000 or end_ms % 60000 or start_ms >= end_ms:
        raise ValueError('Choose increasing, whole UTC minute boundaries')
    book = {'bids': {}, 'asks': {}}
    samples, last_ts, seed_time = [], None, None

    def sample(ts, source_ts, action, values):
        return {'time_ms': ts, 'role': 'ORDER_BOOK', 'payload': {
            'sample_index': len(samples) + 1, 'sample_time_ms': source_ts,
            'snapshot': action == 'snapshot', 'depth_complete': False,
            'depth_scope': 'BOUNDED_SAMPLED', **values}}

    for row in book_records(book_path):
        ts = int(row['ts'])
        if row['instId'] != 'BTC-USDT' or row['action'] not in {'snapshot', 'update'}:
            raise ValueError('Unexpected orderbook record')
        if last_ts is not None and ts <= last_ts:
            raise ValueError('Book timestamps must increase')
        if ts >= end_ms:
            break
        if last_ts is None and row['action'] != 'snapshot':
            raise ValueError('Book archive must start with snapshot')
        last_ts = ts
        values = {side: [[v[0], v[1]] for v in row[side]] for side in book}
        if ts < start_ms:
            for side in book:
                if row['action'] == 'snapshot':
                    book[side] = {}
                for price, qty in values[side]:
                    if Decimal(qty): book[side][price] = qty
                    else: book[side].pop(price, None)
            seed_time = ts
            continue
        if not samples:
            if seed_time is None or start_ms - seed_time > 2000:
                raise ValueError('Window needs a prior book sample no older than 2000 ms; start later')
            initial = {side: [[p, q] for p, q in sorted(book[side].items(), key=lambda v: Decimal(v[0]), reverse=side == 'bids')] for side in book}
            samples.append(sample(start_ms, seed_time, 'snapshot', initial))
        samples.append(sample(ts, ts, row['action'], values))
    if not samples:
        raise ValueError('No book samples in selected range')
    trades, bars, previous_id, previous_ts = [], {}, None, None
    for row in trade_records(trade_paths):
        ts = int(row['created_time'])
        if not start_ms <= ts < end_ms:
            continue
        seq = int(row['trade_id'])
        if row['instrument_name'] != 'BTC-USDT' or row['side'] not in {'buy', 'sell'}:
            raise ValueError('Unexpected trade instrument or side')
        if previous_id is not None and (seq != previous_id + 1 or ts < previous_ts):
            raise ValueError('Trade ID gap, overlap, or reversed time in requested window')
        previous_id, previous_ts = seq, ts
        price, qty = Decimal(row['price']), Decimal(row['size'])
        if not price.is_finite() or not qty.is_finite() or price <= 0 or qty <= 0:
            raise ValueError('Invalid trade price/quantity')
        trades.append({'time_ms': ts, 'role': 'TRADES', 'payload': {'source_event_kind': 'RAW_TRADE',
                       'source_sequence': seq, 'price': str(price), 'qty': str(qty), 'aggressor_side': row['side'].upper()}})
        minute = ts // 60000 * 60000
        if minute not in bars:
            bars[minute] = dict(time=minute, open=price, high=price, low=price, close=price, volume=Decimal(0))
        bar = bars[minute]
        bar.update(high=max(bar['high'], price), low=min(bar['low'], price), close=price, volume=bar['volume'] + qty)
    if set(bars) != set(range(start_ms, end_ms, 60000)):
        raise ValueError('Trade coverage misses one or more chart minutes')
    # Seed is prior information. At all other ties prints precede new samples.
    events = [samples[0], *sorted([*samples[1:], *trades], key=lambda e: (e['time_ms'], e['role'] == 'ORDER_BOOK'))]
    provenance = {'source': 'OKX_PUBLIC_HISTORICAL_ARCHIVE', 'instrument': 'BTC-USDT', 'market': 'SPOT',
                  'fill_model': MODEL, 'book_snapshot_level_limit': 5000, 'nominal_sample_ms': 1000,
                  'exchange_sequence_verified': False, 'source_url': 'https://www.okx.com/zh-hans/historical-data',
                  'start_time_ms': start_ms, 'end_time_ms_exclusive': end_ms, 'seed_sample_time_ms': seed_time,
                  'trade_date_timezone': 'UTC+08:00', 'book_date_timezone': 'UTC',
                  'sample_index_meaning': 'local archive record index, not exchange sequence',
                  'archives': [{'file': p.name, 'sha256': file_hash(p), 'bytes': p.stat().st_size} for p in [book_path, *trade_paths]]}
    return list(bars.values()), {'symbol': 'BTCUSDT', 'events': events, 'provenance': provenance}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--start', required=True, help='UTC ISO timestamp, e.g. 2026-06-01T00:01:00Z')
    parser.add_argument('--minutes', type=int, default=10, help='Selected window; 10 minutes by default')
    parser.add_argument('--download', action='store_true', help='Fetch public 5000-level book and two trade archives')
    parser.add_argument('--resolve', action='append', default=[], help='Optional curl DNS override host:443:IP; TLS still verified')
    args = parser.parse_args()
    start = datetime.fromisoformat(args.start.replace('Z', '+00:00'))
    if start.tzinfo is None:
        parser.error('--start needs an explicit timezone')
    start = start.astimezone(timezone.utc)
    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(minutes=args.minutes)
    if args.minutes <= 0 or end > day + timedelta(days=1):
        parser.error('Choose a positive window within one UTC book day')
    if args.download:
        download_day(args.archive_dir, day, args.resolve)
    book_path = args.archive_dir / f'BTC-USDT-L2orderbook-5000lv-{day:%Y-%m-%d}.tar.gz'
    trade_paths = [args.archive_dir / f'BTC-USDT-trades-{d:%Y-%m-%d}.zip' for d in (day, day + timedelta(days=1))]
    bars, execution = convert(book_path, trade_paths, int(start.timestamp()*1000), int(end.timestamp()*1000))
    encoded = json.dumps(execution, separators=(',', ':'), ensure_ascii=False)
    if len(execution['events']) > 500000 or len(encoded.encode()) > 48 * 1024 * 1024:
        raise ValueError('Selected window exceeds host request budget; choose fewer minutes')
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / 'bars.csv').open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=['time', 'open', 'high', 'low', 'close', 'volume'])
        writer.writeheader(); writer.writerows(bars)
    (args.output / 'execution.json').write_text(encoded, encoding='utf-8')
    manifest = {**execution['provenance'], 'fidelity': 'BOOK_SAMPLED', 'bars': len(bars),
                'events': len(execution['events']), 'execution_sha256': file_hash(args.output / 'execution.json'),
                'bars_sha256': file_hash(args.output / 'bars.csv'), 'csv_timestamp_unit': 'ms'}
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps(manifest))


if __name__ == '__main__':
    main()
