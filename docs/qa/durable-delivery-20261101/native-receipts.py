"""Controlled publication recovery in an isolated native QA profile only.

Insert committed receipts for existing real canonical candles atomically. No
canonical candle is changed. This is not evidence of 64 new exchange events.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time
import uuid

root = Path(sys.argv[1]).resolve()
assert root.name.startswith('durable-delivery-native-') and root.parent.name == 'output'
database = root / 'profile/data/candlescope.db'
assert database.is_file()
manifest = root / 'controlled-receipts.json'
connection = sqlite3.connect(database, timeout=10)
connection.row_factory = sqlite3.Row


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(rows):
    return hashlib.sha256(encoded(rows).encode()).hexdigest()


if sys.argv[2] == 'insert':
    assert not manifest.exists(), 'Do not silently replace a prior recovery fixture'
    from app.data_engine.storage.revisions import current_revision
    with connection:
        connection.execute('BEGIN IMMEDIATE')
        rows = []
        for symbol in ('BTCUSDT', 'ETHUSDT'):
            selected = connection.execute("SELECT * FROM klines WHERE exchange='binance' AND market_type='spot' AND symbol=? AND interval='1m' AND close_time<? ORDER BY open_time DESC LIMIT 32", (symbol, int(time.time() * 1000) - 120000)).fetchall()
            assert len(selected) == 32
            rows.extend(dict(row) for row in reversed(selected))
        revision = current_revision(connection)
        ids = []
        fields = ('open', 'high', 'low', 'close', 'volume', 'quote_volume', 'trades', 'taker_buy_base', 'taker_buy_quote', 'source')
        identity = ('exchange', 'market_type', 'symbol', 'interval', 'provider_id', 'venue', 'asset_class', 'series_variant', 'price_adjustment', 'session_variant', 'volume_semantics')
        for row in rows:
            event_id = 'native-ack-qa-' + uuid.uuid4().hex
            bar = {name: row[name] for name in fields}
            bar.update(time=row['open_time'] // 1000, is_closed=True)
            payload = {name: row[name] for name in identity}
            payload.update(event_type='bar.closed', bar=bar, storage_row=row,
                           timestamp_ms=int(time.time() * 1000), derived=False,
                           detail={'qa': 'controlled committed-publication recovery'})
            connection.execute("INSERT INTO bar_delivery(event_id,payload,phase,created_ms,observed_revision,committed_revision,recovery_required) VALUES (?,?,'committed',?,?,?,0)",
                               (event_id, encoded(payload), int(time.time() * 1000), revision, revision))
            ids.append(event_id)
    evidence = {'purpose': 'Controlled recovery receipts for 64 real previously stored candles; canonical rows untouched', 'event_ids': ids, 'canonical_rows': rows, 'canonical_sha256': digest(rows), 'revision': revision}
    manifest.write_text(json.dumps(evidence, indent=2) + '\n')
    print(json.dumps({'count': len(ids), 'canonical_sha256': evidence['canonical_sha256'], 'revision': revision}))
elif sys.argv[2] == 'check':
    evidence = json.loads(manifest.read_text())
    rows = []
    for original in evidence['canonical_rows']:
        names = ('exchange', 'market_type', 'symbol', 'interval', 'provider_id', 'venue', 'asset_class', 'series_variant', 'price_adjustment', 'session_variant', 'volume_semantics', 'open_time')
        row = connection.execute('SELECT * FROM klines WHERE ' + ' AND '.join(name + '=?' for name in names), tuple(original[name] for name in names)).fetchone()
        assert row is not None
        rows.append(dict(row))
    assert digest(rows) == evidence['canonical_sha256'], 'Recovery changed canonical candles'
    placeholders = ','.join('?' for _ in evidence['event_ids'])
    phases = dict(connection.execute(f'SELECT phase,COUNT(*) FROM bar_delivery WHERE event_id IN ({placeholders}) GROUP BY phase', evidence['event_ids']).fetchall())
    print(json.dumps({'phases': phases, 'canonical_sha256': digest(rows), 'passed': phases == {'published': 64}}))
else:
    raise ValueError('Unknown operation')
connection.close()
