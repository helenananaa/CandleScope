"""Bounded public OKX capture, with exchange continuity and raw-file receipts.

books = 400 levels / 100ms; trades-all uses a separate connection. Neither this
feed nor host receive order proves complete-market depth or exchange FIFO.
Disconnects/sequence resets invalidate the segment. Rerun into a new directory.
"""
from __future__ import annotations
import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import socket
import threading
import time
from websockets.sync.client import connect


class BookChain:
    def __init__(self):
        self.seq = None
        self.book = {'bids': {}, 'asks': {}}
        self.snapshots = self.updates = 0

    def accept(self, action, row):
        seq, prev = row['seqId'], row['prevSeqId']
        if type(seq) is not int or type(prev) is not int:
            raise ValueError('Non-integer exchange book sequence')
        if self.seq is None:
            if action != 'snapshot' or prev != -1:
                raise ValueError('Missing initial exchange snapshot')
        elif action != 'update' or prev != self.seq or seq < self.seq:
            raise ValueError('Exchange sequence gap/reset or unsolicited snapshot')
        elif seq == self.seq and (row['asks'] or row['bids']):
            raise ValueError('Repeated sequence with changed book')
        for side in self.book:
            for level in row[side]:
                price, qty = level[:2]
                p, q = Decimal(price), Decimal(qty)
                if not p.is_finite() or not q.is_finite() or p <= 0 or q < 0:
                    raise ValueError('Invalid book level')
                if q: self.book[side][price] = qty
                else: self.book[side].pop(price, None)
        # Official production protocol changed on 2026-06-23: checksum is fixed
        # to zero and MUST NOT be used as an integrity check. Keep raw values.
        if not self.book['bids'] or not self.book['asks']:
            raise ValueError('Incomplete two-sided book')
        self.seq = seq
        self.snapshots += action == 'snapshot'
        self.updates += action == 'update'


def capture(directory, seconds, resolve_ip=None):
    directory.mkdir(parents=True,exist_ok=True)
    frames_path=directory/'frames.jsonl'
    stop,lock=threading.Event(),threading.Lock()
    chain=BookChain()
    stats={'book_messages':0,'trades':0,'last_trade_id':None,'errors':[]}
    began=time.time_ns()
    deadline=time.monotonic()+seconds
    # Exclusive creation preserves earlier evidence on accidental reruns.
    with frames_path.open('x',encoding='utf-8') as frames:
        def reader(channel, endpoint):
            try:
                options={'proxy':None,'open_timeout':15,'close_timeout':3,'max_size':8*1024*1024}
                if resolve_ip:
                    options['sock']=socket.create_connection((resolve_ip,8443),timeout=15)
                with connect(f'wss://ws.okx.com:8443/ws/v5/{endpoint}',**options) as ws:
                    ws.send(json.dumps({'op':'subscribe','args':[{'channel':channel,'instId':'BTC-USDT'}]}))
                    while not stop.is_set() and time.monotonic()<deadline:
                        try: raw=ws.recv(timeout=min(1,max(.01,deadline-time.monotonic())))
                        except TimeoutError: continue
                        with lock:
                            frames.write(json.dumps({'channel':channel,'received_time_ns':time.time_ns(),
                                'received_monotonic_ns':time.monotonic_ns(),'raw':raw})+'\n'); frames.flush()
                            if raw=='pong': continue
                            message=json.loads(raw)
                            if message.get('event')=='error': raise ValueError(f'OKX subscription rejected: {message}')
                            if 'data' not in message: continue
                            if message.get('arg',{}).get('instId')!='BTC-USDT': raise ValueError('Unexpected symbol')
                            for row in message['data']:
                                if channel=='books':
                                    chain.accept(message['action'],row); stats['book_messages']+=1
                                else:
                                    seq=int(row['tradeId'])
                                    if stats['last_trade_id'] is not None and seq!=stats['last_trade_id']+1:
                                        raise ValueError('Raw trade ID gap/reset')
                                    if row['side'] not in {'buy','sell'}: raise ValueError('Unknown trade side')
                                    stats['last_trade_id']=seq; stats['trades']+=1
            except Exception as exc:
                with lock: stats['errors'].append({'channel':channel,'message':f'{type(exc).__name__}: {exc}'})
                stop.set()
        workers=[threading.Thread(target=reader,args=pair) for pair in [('books','public'),('trades-all','business')]]
        for worker in workers: worker.start()
        try:
            for worker in workers: worker.join()
        except KeyboardInterrupt:
            stop.set()
            for worker in workers: worker.join()
            stats['errors'].append({'channel':'collector','message':'Interrupted; partial capture'})
    valid=not stats['errors'] and chain.snapshots==1 and chain.updates>0 and stats['trades']>0
    with frames_path.open('rb') as stream:
        raw_sha256=hashlib.file_digest(stream,'sha256').hexdigest()
    receipt={'schema':'candlescope.okx-live-capture/1','started_time_ns':began,'finished_time_ns':time.time_ns(),
        'requested_seconds':seconds,'status':'CONTINUOUS_BOUNDED_FEED' if valid else 'INCOMPLETE',**stats,
        'continuity_check':'seqId/prevSeqId', 'checksum_status':'deprecated_by_OKX_2026-06-23_not_used',
        'last_book_seq_id':chain.seq,
        'depth_levels':400,'nominal_book_interval_ms':100,'book_depth_admissible':False,
        'limits':['bounded 400 levels, not complete market depth','100ms feed, not every matching-engine event',
                  'two connections; receive order is not exchange cross-stream ordering','no order-level FIFO priority'],
        'source':'https://www.okx.com/docs-v5/en/#order-book-trading-market-data-ws-order-book-channel',
        'checksum_deprecation_source':'https://www.okx.com/zh-hans/help/okx-order-book-channels-checksum-field-deprecation',
        'raw_sha256':raw_sha256}
    (directory/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2),encoding='utf-8')
    return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--seconds',type=int,default=60)
    parser.add_argument('--resolve-ip',help='Optional ws.okx.com IP; TLS hostname verification remains enabled')
    args=parser.parse_args()
    if not 1<=args.seconds<=86400: parser.error('--seconds must be between 1 and 86400')
    receipt=capture(args.output,args.seconds,args.resolve_ip)
    print(json.dumps(receipt,ensure_ascii=False))
    raise SystemExit(0 if receipt['status']=='CONTINUOUS_BOUNDED_FEED' else 1)
