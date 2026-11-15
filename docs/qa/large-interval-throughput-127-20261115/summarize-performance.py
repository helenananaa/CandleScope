"""Summarize native receipts without conflating RSS and macOS footprint."""
import argparse
from collections import Counter
from datetime import datetime
import json
import math
from pathlib import Path
from statistics import median
from urllib.parse import urlparse, parse_qs


def milliseconds(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()*1000


def latency(rows):
    values = sorted(row['elapsedMs'] for row in rows if row.get('elapsedMs') is not None)
    return ({'count': len(values), 'p50_ms': median(values),
             'p95_ms': values[math.ceil(len(values)*.95)-1], 'max_ms': values[-1]}
            if values else {'count': 0})


def summarize(path):
    acceptance = json.loads((path/'acceptance.json').read_text())
    traffic = json.loads((path/'traffic.json').read_text())
    resources = [json.loads(line) for line in (path/'resource-samples.jsonl').read_text().splitlines()]
    steps = acceptance['steps']
    step = lambda name: next(item for item in steps if item['name'] == name)
    cold = step('cold-prime-targets')
    cold_end = milliseconds(cold['at'])
    cold_start = cold_end-cold['evidence']['elapsedMs']
    steady_start = milliseconds(step('live-frames-cold-primes')['at'])
    steady_end = milliseconds(step('prime-steady-minute-10')['at'])
    def requests(start, end):
        return [row for row in traffic['requests'] if start <= row['at'] <= end]
    def responses(start, end):
        return [row for row in traffic['responses'] if start <= (row.get('startedAt') or row['observedAt']) <= end]
    def phase(start, end):
        sent = requests(start, end)
        received = responses(start, end)
        builtin = [row for row in sent if '/indicators/compute/batch' in row['url']]
        composed = [row for row in sent if '/range/composed' in row['url'] and 'interval=10007m' in row['url']]
        return {'duration_ms': round(end-start), 'requests': len(sent),
                'builtin_http_requests': len(builtin),
                'builtin_request_body_bytes': sum(len(row['body']) for row in builtin),
                'composed_10007m_requests': len(composed),
                'history_latency': latency([row for row in received if '/klines/' in row['url']]),
                'endpoints': dict(Counter(urlparse(row['url']).path for row in sent))}
    peak = max(resources, key=lambda row: row['rssKiB'])
    steady_resources = [row for row in resources if steady_start <= milliseconds(row['at']) <= steady_end]
    footprints = {}
    for filename in sorted(path.glob('footprint-*.json')):
        receipt = json.loads(filename.read_text())
        footprints[filename.stem] = {'bytes': receipt['total footprint'],
            'processes': len(receipt['processes']), 'errors': receipt['errors']}
    strict = [row for row in traffic['responses'] if '/klines/range?' in row['url']
        and parse_qs(urlparse(row['url']).query).get('interval') == ['10007m']
        and parse_qs(urlparse(row['url']).query).get('strict') == ['true']]
    return {'directory': str(path), 'product_commit': acceptance['sourceCommit'],
        'passed': acceptance['passed'], 'errors': acceptance['errors'],
        'cold': phase(cold_start, cold_end), 'steady': phase(steady_start, steady_end),
        'cold_storage': cold['evidence']['diagnostics']['storage']['series']['by_interval'],
        'resources': {'rss_scope': 'owned process RSS sum; shared pages can repeat; not private footprint',
            'peak_rss_kib': peak['rssKiB'], 'peak_rss_phase': peak['phase'],
            'max_processes': max(len(row['processes']) for row in resources),
            'steady_max_processes': max(len(row['processes']) for row in steady_resources),
            'steady_peak_rss_kib': max(row['rssKiB'] for row in steady_resources),
            'steady_first_rss_kib': steady_resources[0]['rssKiB'],
            'steady_last_rss_kib': steady_resources[-1]['rssKiB'],
            'macos_footprint': footprints},
        'strict_10007m_reads': [{'elapsed_ms': row['elapsedMs'],
            'complete': row.get('result', {}).get('complete'),
            'canonical': (row.get('result', {}).get('metadata') or {}).get('canonical_target_snapshot')}
            for row in strict],
        'http_5xx': sum(row['status'] >= 500 for row in traffic['responses'])}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('runs', nargs='+', type=Path)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    result = {'schema': 'candlescope.native-performance-comparison/1',
        'scope': 'sequential native runs against real public data; not a controlled network/ambient-load pair',
        'runs': [summarize(path) for path in args.runs]}
    encoded = json.dumps(result, indent=2)+'\n'
    if args.out:
        args.out.write_text(encoded)
    else:
        print(encoded, end='')
