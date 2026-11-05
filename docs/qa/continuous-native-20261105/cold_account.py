"""Read an exited synthetic profile without opening an execution owner."""
from pathlib import Path
import argparse
import hashlib
import json
import sqlite3

parser=argparse.ArgumentParser();parser.add_argument('--profile',required=True);args=parser.parse_args()
profile=Path(args.profile).resolve();seed=json.loads((profile/'seed-receipt.json').read_text())
database=profile/'data/continuous-strategy.sqlite3';assert database.is_file()
wal=database.with_name(database.name+'-wal');assert not wal.exists() or wal.stat().st_size==0,'Wait for all owners to exit and checkpoint WAL'
sha=lambda value:hashlib.sha256(value).hexdigest()
before=sha(database.read_bytes());db=sqlite3.connect(database.as_uri()+'?mode=ro&immutable=1',uri=True);db.row_factory=sqlite3.Row
try:
    db.execute('PRAGMA query_only=ON')
    row=db.execute('SELECT r.*,c.wire,c.sequence AS cp_sequence,c.event_time_ms AS cp_time,c.data_revision AS cp_data_revision '
        'FROM runs r JOIN checkpoints c ON c.run_id=r.id AND c.revision=r.checkpoint_revision WHERE r.id=?',(seed['runId'],)).fetchone()
    assert row is not None and (row['sequence'],row['event_time_ms'],row['data_revision'])==(row['cp_sequence'],row['cp_time'],row['cp_data_revision'])
    fields='id,mode,generation,revision,phase,sequence,event_time_ms,data_revision,checkpoint_revision,error_json,updated_at_ms'.split(',')
    summary={field:row[field] for field in fields};summary['error']=json.loads(summary.pop('error_json') or 'null')
    definition=json.loads(row['definition_json'])
    epoch=db.execute('SELECT e.source_owner,e.initial_snapshot_json FROM continuous_epochs e JOIN active_continuous_epochs a '
        'ON a.epoch_id=e.id WHERE a.run_id=?',(seed['runId'],)).fetchone()
    if epoch is not None:
        definition['source_owner']=epoch['source_owner']
        if epoch['initial_snapshot_json'] is None:definition.pop('initial_snapshot',None)
        else:definition['initial_snapshot']=json.loads(epoch['initial_snapshot_json'])
    saved={'run':summary,'definition':definition,'checkpoint':json.loads(row['wire'])}
    assert saved==seed['saved'],'Saved complete account changed'
    digest=sha(json.dumps(saved,sort_keys=True,separators=(',',':')).encode());assert digest==seed['savedSha256']
finally:db.close()
assert sha(database.read_bytes())==before,'Read-only witness changed database bytes'
print(json.dumps({'profile':str(profile),'runId':seed['runId'],'savedSha256':digest,'matchesSeed':True,
    'databaseBytesUnchanged':True,'phase':summary['phase'],'sequence':summary['sequence']}))
