"""Run unchanged public-path probes against a chosen checkout, including pre-K130."""
import argparse
from datetime import datetime
import json
from pathlib import Path
import sys
p = argparse.ArgumentParser()
p.add_argument('root', type=Path)
args = p.parse_args()
sys.path.insert(0, str(args.root / 'backend'))
from app.data_engine.bar_aggregator.bar_state import has_complete_closed_component_coverage
from app.data_engine.bar_aggregator.models import BarState
from app.data_engine.data_manager.models import BarData
from app.data_engine.data_manager.custom_query import _aggregate_fixed_bars_to_interval
from app.data_engine.history.calendar import SessionCalendar, expected_bucket_end_ms
from app.data_engine.interval_policy import aggregate_kline_rows, parse_interval_spec

checks = {}
bars = [BarData(time=t, open=1., high=2., low=1., close=1.5, volume=1.) for t in (0, 180)]
checks['history_crossing_source_not_closed'] = not _aggregate_fixed_bars_to_interval(
    bars, 300, source_interval_seconds=180)[0].is_closed
state = BarState(symbol='BTCUSDT', interval='5m', bucket_start_ms=0, bucket_end_ms=300000,
                 open=1, high=2, low=1, close=1.5, volume=2,
                 source_snapshots={str(t): dict(open_time_ms=t, close_time_ms=t+179999,
                                               is_closed=True) for t in (0, 180000)})
checks['live_crossing_source_not_closed'] = not has_complete_closed_component_coverage(state)
start = int(datetime.fromisoformat('2024-01-01T00:00+00:00').timestamp()*1000)
source = parse_interval_spec('1M'); target = parse_interval_spec('12M')
rows=[]; opened=start
for i in range(12):
    ended=source.next_ms(opened)
    rows.append(dict(open_time=opened, close_time=ended-1, open=1., high=2., low=1.,
                     close=1.5, volume=i+1., is_closed=True))
    opened=ended
out=aggregate_kline_rows(rows,target_interval='12M',source_interval='1M',now_ms=target.next_ms(start))
checks['strict_month_source_uses_actual_end'] = len(out)==1 and out[0]['volume']==78
rows=[dict(open_time=i*60000,close_time=(i+1)*60000-1,open=1.000000001,high=2.,low=1.,
           close=1.1,volume=.000000001,is_closed=True) for i in range(100)]
rebuilt=aggregate_kline_rows(rows,target_interval='100m',source_interval='1m',now_ms=6000000)[0]
queried=_aggregate_fixed_bars_to_interval([BarData.from_storage_row(row) for row in rows],6000,
                                          source_interval_seconds=60)[0]
checks['raw_and_decoded_leaf_precision_match'] = rebuilt['volume']==queried.volume==0
calendar=SessionCalendar(calendar_id='probe.ny',timezone_name='America/New_York',
                         weekly_sessions={day:(('09:30','16:00'),) for day in range(5)})
opened=int(datetime.fromisoformat('2024-02-29T14:30+00:00').timestamp()*1000)
ended=int(datetime.fromisoformat('2024-03-01T00:00+00:00').timestamp()*1000)
checks['session_daily_label_keeps_canonical_end'] = expected_bucket_end_ms(calendar,opened,'1d')==ended
print(json.dumps({'root':str(args.root),'checks':checks},indent=2))
