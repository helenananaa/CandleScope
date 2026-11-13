"""Compare bounded native producer attempts with public consumer observations."""
import argparse
import collections
import json
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('input', type=Path)
parser.add_argument('output', type=Path)
args = parser.parse_args()
records = [json.loads(line) for line in args.input.read_text().splitlines()]
attempts = collections.defaultdict(list)
delivered = collections.defaultdict(list)
registrations = [r for r in records if r['kind'] == 'registered']
for row in records:
    group = (row['pid'], row.get('key'))
    if row['kind'] == 'attempt':
        attempts[group].append(row)
    elif row['kind'] == 'delivered':
        delivered[group].append(row['attempt'])
groups, bursts = [], set()
for group, rows in attempts.items():
    required = [r['attempt'] for r in rows]
    observed = [identifier for identifier in delivered[group] if identifier in set(required)]
    interval = rows[0]['interval']
    if any(0 <= b['wall_ms']-a['wall_ms'] < 10000 for a, b in zip(rows, rows[1:])):
        bursts.add(interval)
    groups.append({'pid': group[0], 'key': group[1], 'interval': interval,
                   'attempts_total': len(rows),
                   'expected_ids': required, 'observed_ids': observed,
                   'matches': observed == required})
per_pid = collections.Counter(r['pid'] for r in records if r['kind'] == 'attempt')
passed = (bool(groups) and all(g['matches'] for g in groups) and all(n < 256 for n in per_pid.values())
          and {'45m', '90m'} <= bursts and len(registrations) == 2
          and all(r['throttle_ms'] == 10000 for r in registrations))
args.output.write_text(json.dumps({'passed': passed, 'groups': groups, 'attempts_per_pid': dict(per_pid),
    'burst_intervals_within_10s': sorted(bursts), 'registrations': registrations,
    'scope': 'instrumented native public consumer, matched scalar fingerprints; all recorded attempts without tail exclusion, cap not reached; not performance/endurance/canonical-ack qualification'}, indent=2)+'\n')
if not passed:
    raise SystemExit('native update preservation witness failed')
print(json.dumps({'passed': passed, 'observations': sum(g['attempts_total'] for g in groups)}))
