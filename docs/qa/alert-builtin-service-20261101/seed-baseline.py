"""Pin legacy alias semantics before replacing the alert-owned calculators."""
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import subprocess

from app.alerts.indicator_context import compute_alert_indicator_values
from app.data_engine.data_manager.models import BarData
from app.indicator import create_engine

ROOT = Path(__file__).resolve().parents[3]
definitions = {
    'rsi': ('RSI', {'period': 14, 'source': 'close'}, 'rsi'),
    'macdHist': ('MACD', {'fast': 12, 'slow': 26, 'signal': 9, 'source': 'close'}, 'hist'),
    'ma20': ('MA', {'period': 20, 'source': 'close'}, 'ma'),
}
bars = [BarData(time=1_780_000_020 + i * 60, open=100 + i / 20,
               high=130 + i / 20, low=70 + i / 20,
               close=100 + i / 20 + 20 * math.sin(i / 57) + 3 * math.sin(i / 3),
               volume=10 + i % 5, is_closed=True, source='backfill')
        for i in range(1000)]
engine = create_engine()
cases = []
try:
    for end in (20, 35, 60, 249, 250, 251, 400, 700, 1000):
        for forming in (False, True):
            # Legacy retains at most250 slots including a forming slot, then
            # filters closed bars. Its update view therefore has at most249.
            window = bars[max(0, end - 250):end]
            if forming:
                window = [*window[:-1], replace(window[-1], is_closed=False)]
            closed = [bar for bar in window if bar.is_closed]
            legacy = compute_alert_indicator_values(closed)
            public, long_seed = {}, {}
            for field, (name, params, output) in definitions.items():
                public[field] = engine.compute('BTCUSDT', '1m', 'spot', name, params, closed).get_latest()[output]
                long_seed[field] = engine.compute('BTCUSDT', '1m', 'spot', name, params,
                                                   bars[:end - int(forming)]).get_latest()[output]
                assert legacy[field] == public[field], (end, forming, field)
            cases.append(dict(end=end, forming=forming, closed_count=len(closed),
                              legacy=legacy, same_seed_public=public, long_seed_public=long_seed,
                              changed_with_long_seed=[field for field in definitions
                                                      if legacy[field] != long_seed[field]]))
finally:
    engine.stop()
assert any('rsi' in case['changed_with_long_seed'] for case in cases)
assert any('macdHist' in case['changed_with_long_seed'] for case in cases)
out = dict(source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
           input_sha256=hashlib.sha256(repr(bars).encode()).hexdigest(),
           transport='Controlled deterministic bars; actual legacy calculators and public IndicatorEngine. No notifications or network.',
           policy='legacy_confirmed_rolling250_v1', definitions=definitions, cases=cases,
           conclusions=['Public formulas preserve legacy values with the same input window.',
                        'Rolling250 and long recursive seeds are incompatible calculation identities.',
                        'A forming slot consumes window capacity even though indicator values are confirmed-only.',
                        'MA-only finite windows may be shareable; do not infer RSI/MACD sharing from matching names.'])
path = ROOT / 'output/alert-builtin-service-20261101/seed-baseline.json'
path.write_text(json.dumps(out, indent=2) + '\n')
print(json.dumps(dict(cases=len(cases), same_seed_equal=True,
                     different_seed_cases=sum(bool(case['changed_with_long_seed']) for case in cases))))
