"""Versioned review projections of verified OKX lifecycles, never an editable ledger."""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal, localcontext

from app.trading_accounts.journal import phase_at, trade_metrics
from app.trading_accounts.journal_service import JournalService
from app.trading_accounts.models import invalid, not_found, now_ms
from app.trading_accounts.store import TradingStore
from app.trading_accounts.trades import Trade
from .normalization import AccountDataError, exact
from .reconciliation import reconcile_account
from .repository import AccountRepository, canonical

ZERO = Decimal(0)


def identity(prefix, parts):
    return prefix + '_' + hashlib.sha256(canonical(parts).encode()).hexdigest()[:20]


class ReviewTrade(Trade):
    """Journal timing adapter; financial facts remain the verified projection."""
    def __init__(self, view):
        super().__init__(id=view['id'], account_id=view['accountId'], exchange='okx',
                         market_type='futures', symbol=view['symbol'], direction=view['direction'],
                         opened_at_ms=view['openedAtMs'], closed_at_ms=view['closedAtMs'],
                         entry_qty=Decimal(view['entryQty']), max_qty=Decimal(view['maxQty']),
                         entry_cost=Decimal(view['entryQty'])*Decimal(view['avgEntryPrice']),
                         realized_pnl=Decimal(view['realizedPnl']), fees=Decimal(view['fees']))
        self.view = view

    @property
    def avg_entry_price(self):
        return Decimal(self.view['avgEntryPrice'])

    @property
    def net_pnl(self):
        return Decimal(self.view['netPnl'])

    def to_dict(self, **_):
        return dict(self.view)


class ReadOnlyReview(JournalService):
    def __init__(self, repository: AccountRepository, *, clock=now_ms):
        self.repository = repository
        store = TradingStore(repository.root / 'review-journal.sqlite3')
        super().__init__(store, snapshot_dir=repository.root / 'review-snapshots', clock=clock)
        with store.transaction() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS review_version(
                seq INTEGER PRIMARY KEY AUTOINCREMENT, trade_id TEXT NOT NULL,
                account_id TEXT NOT NULL, version TEXT NOT NULL, verified_ms INTEGER NOT NULL,
                payload TEXT NOT NULL, UNIQUE(trade_id,version))''')
            db.execute('''CREATE TABLE IF NOT EXISTS review_head(
                trade_id TEXT PRIMARY KEY, version TEXT NOT NULL)''')
        store.path.chmod(0o600)

    def account_id(self):
        account = self.repository.account()
        return identity('acc', ['okx', account['venue_uid']]) if account else None

    def _account(self, account_id):
        if account_id != self.account_id():
            raise not_found('Account')
        return super()._account(account_id)

    def _ensure_account(self, account_id):
        with self.store.transaction() as db:
            db.execute('''INSERT OR IGNORE INTO accounts VALUES(?,?,?,?,?,?,?)''',
                       (account_id, 'exchange_readonly', 'OKX', 'USDT', '{}', self.clock(), 0))

    def _trades(self, account_id):
        self._account(account_id)
        return [ReviewTrade(json.loads(row['payload'])) for row in self.store.all('''
            SELECT v.* FROM review_version v JOIN review_head h
            ON h.trade_id=v.trade_id AND h.version=v.version WHERE v.account_id=? ORDER BY v.seq''', (account_id,))]

    def refresh(self):
        """Only fresh, fully evidenced cycles may create a new immutable version."""
        with self.store.locked(), localcontext() as context:
            context.prec = 80
            try:
                data = self.repository.reconciliation_inputs()
            except AccountDataError as exc:
                account_id = self.account_id()
                trades = [trade.to_dict() for trade in self._trades(account_id)] if account_id and self.store.account(account_id) else []
                for trade in trades:
                    trade['readonlySource']['current'] = False
                return {'trades': trades, 'excluded': [], 'current': False, 'readError': exc.code,
                        'coverage': self.repository.coverage(), 'gaps': self.repository.gaps(),
                        'truncated': True, 'stats': self.stats(trades)}
            account = data.get('account')
            if not account:
                return {'trades': [], 'excluded': [], 'current': False, 'coverage': [],
                        'gaps': [], 'truncated': False, 'stats': self.stats([])}
            uid = self.repository.account()['venue_uid']
            account_id = identity('acc', ['okx', uid])
            self._ensure_account(account_id)
            report = reconcile_account(data, now_ms=self.clock(), include_evidence=True)
            fills = {item['value']['fillId']: item for item in data['facts'] if item['kind'] == 'fills'}
            funding = {row['billId']: row for row in report['funding']}
            verified, excluded = set(), []
            for cycle in report['positions']:
                selected = [fills[key] for key in cycle['fillIds']]
                reason = cycle['reason']
                if any(item['value']['contract']['kind'] != 'linear' for item in selected) or cycle['currency'] != 'USDT':
                    reason = 'unsupportedPosition'
                elif (report['truncated'] or not report['current'] or not report['historyReady']
                      or cycle['endMs'] is None or cycle['endMs'] > self.clock()):
                    reason = 'historyUnavailable'
                elif report['fees']['status'] != 'matched':
                    reason = 'amountMismatch'
                if reason or cycle['status'] != 'matched' or not selected:
                    excluded.append({'positionId': cycle['id'], 'instrument': cycle['instrument'],
                                     'reason': reason or 'openingUnknown'})
                    continue
                view = self._project(account_id, uid, cycle, selected, funding)
                digest = hashlib.sha256(canonical(view).encode()).hexdigest()
                view['readonlySource'].update(version=digest, verifiedAtMs=self.clock())
                with self.store.transaction() as db:
                    db.execute('''INSERT OR IGNORE INTO review_version
                        (trade_id,account_id,version,verified_ms,payload) VALUES(?,?,?,?,?)''',
                        (view['id'], account_id, digest, self.clock(), canonical(view)))
                    db.execute('INSERT OR REPLACE INTO review_head VALUES(?,?)', (view['id'], digest))
                verified.add((view['id'], digest))
            trades = [trade.to_dict() for trade in self._trades(account_id)]
            for trade in trades:
                trade['readonlySource']['current'] = (trade['id'], trade['readonlySource']['version']) in verified
            trades.sort(key=lambda trade: (trade['openedAtMs'], trade['id']), reverse=True)
            return {'trades': trades, 'excluded': excluded, 'current': report['current'],
                    'coverage': data['coverage'], 'gaps': data['gaps'], 'truncated': report['truncated'],
                    'unmatchedFills': report['counts']['unmatchedFills'], 'stats': self.stats(trades)}

    @staticmethod
    def _project(account_id, uid, cycle, selected, funding):
        # posId can be reused across position lifecycles; cTime distinguishes them.
        trade_id = identity('ro', ['okx', uid, 'SWAP', cycle['instrument'], cycle['positionSide'],
                                   cycle['marginMode'], cycle['id'], cycle['startMs']])
        qty = maximum = entry_qty = entry_cost = exit_qty = exit_value = ZERO
        legs, provenance = [], []
        for item in selected:
            f = item['value']
            q, price = Decimal(f['baseQuantity']), Decimal(f['price'])
            opening = f['effect'] == 'open'
            role = ('open' if qty == 0 else 'add') if opening else ('close' if qty == q else 'reduce')
            qty += q if opening else -q
            maximum = max(maximum, qty)
            if opening:
                entry_qty += q
                entry_cost += q*price
            else:
                exit_qty += q
                exit_value += q*price
            legs.append({'fillId': f['fillId'], 'side': f['side'], 'role': role, 'qty': exact(q),
                         'price': f['price'], 'fee': exact(-Decimal(f['feeCashChange'])),
                         'tsMs': f['eventTimeMs'], 'liquidity': 'exchange', 'orderId': f['orderId']})
            provenance.append({'fillId': f['fillId'], 'tradeId': f['tradeId'], 'orderId': f['orderId'],
                               'contracts': f['contracts'], 'contractValue': f['contract']['contractValue'],
                               'realizedPnl': f['exchangeRealizedPnl'], 'tsMs': f['eventTimeMs']})
        return {'id': trade_id, 'accountId': account_id, 'exchange': 'okx', 'marketType': 'futures',
                'symbol': cycle['instrument'].removesuffix('-SWAP').replace('-', ''),
                'direction': cycle['positionSide'], 'status': 'closed',
                'openedAtMs': min(leg['tsMs'] for leg in legs), 'closedAtMs': max(leg['tsMs'] for leg in legs),
                'openQty': '0', 'maxQty': exact(maximum), 'entryQty': exact(entry_qty), 'exitQty': exact(exit_qty),
                'avgEntryPrice': exact(entry_cost/entry_qty), 'avgExitPrice': exact(exit_value/exit_qty),
                'realizedPnl': cycle['exchangePnl'], 'fees': exact(-Decimal(cycle['fee'])), 'netPnl': cycle['net'],
                'markPrice': None, 'unrealizedPnl': None, 'legs': legs,
                'readonlySource': {'venue': 'okx', 'accountUid': uid, 'product': 'SWAP',
                    'instrument': cycle['instrument'], 'positionId': cycle['id'], 'marginMode': cycle['marginMode'],
                    'currency': 'USDT', 'funding': cycle['funding'], 'fills': provenance,
                    'fundingEvents': [funding[key] for key in cycle['fundingIds']]}}

    @staticmethod
    def stats(trades):
        with localcontext() as context:
            context.prec = 80
            total = lambda key: exact(sum((Decimal(trade[key]) for trade in trades), ZERO))
            return {'currency': 'USDT', 'count': len(trades),
                    'wins': sum(Decimal(trade['netPnl']) > 0 for trade in trades),
                    'realizedPnl': total('realizedPnl'), 'fees': total('fees'), 'netPnl': total('netPnl'),
                    'funding': exact(sum((Decimal(trade['readonlySource']['funding']) for trade in trades), ZERO)),
                    'cachedCount': sum(not trade['readonlySource'].get('current', False) for trade in trades),
                    'rCount': 0, 'averageR': None}

    def trade_detail(self, account_id, trade_id, version=None):
        self._account(account_id)
        if version is None:
            head = self.store.one('SELECT version FROM review_head WHERE trade_id=?', (trade_id,))
            version = head['version'] if head else ''
        clause, args = ' AND version=?', (version,)
        row = self.store.one('''SELECT payload FROM review_version WHERE account_id=? AND trade_id=?'''
                             + clause + ' ORDER BY seq DESC LIMIT 1', (account_id, trade_id, *args))
        if not row:
            raise not_found('Verified trade version')
        trade = ReviewTrade(json.loads(row['payload']))
        entries = self._entries_by_trade(account_id)[0].get(trade_id, [])
        revisions = self.store.revisions_for([entry['id'] for entry in entries])
        note, plan = self._trade_note_and_plan(trade, entries, revisions)
        view = trade.to_dict()
        view.update(noteId=note['id'] if note else None, plan=plan, metrics=trade_metrics(trade, plan),
                    entries=[self._entry_view(entry, revisions.get(entry['id'], []), trade, include_history=True)
                             for entry in entries], linkSuggestions=[])
        view['entries'].extend(self.legacy_entries(view))
        return view

    def _create_entry(self, account_id, payload):
        if not payload.get('tradeId'):
            raise invalid('Read-only reviews must reference a verified closed trade')
        return super()._create_entry(account_id, payload)

    def legacy_entries(self, trade):
        groups = {}
        for row in self.legacy_notes([leg['fillId'] for leg in trade['legs']]):
            groups.setdefault(row['noteId'], []).append(row)
        entries = []
        for note_id, rows in groups.items():
            first, last = rows[0], rows[-1]
            entries.append({'id': 'legacy_' + note_id, 'accountId': trade['accountId'],
                'exchange': 'okx', 'marketType': 'futures', 'symbol': trade['symbol'],
                'kind': 'quick', 'tradeId': trade['id'], 'createdAtMs': first['recordedMs'],
                'updatedAtMs': last['recordedMs'], 'marketTimeMs': last['eventMs'] if last['payload']['kind'] == 'review' else None,
                'templateId': None, 'templateVersion': None, 'tags': last['payload']['tags'],
                'fields': {}, 'body': last['payload']['text'], 'revisionCount': len(rows),
                'revisions': [{'revision': row['version'], 'savedAtMs': row['recordedMs'],
                    'fields': {}, 'body': row['payload']['text'], 'historyComplete': True} for row in rows],
                'stage': phase_at(first['recordedMs'], ReviewTrade(trade)), 'reviewNote': last['payload']['kind'] == 'review',
                'fieldTiming': {}, 'plan': None, 'snapshots': []})
        return entries

    def legacy_notes(self, fill_ids):
        # Preserve the old fill journal and its actual saved times, without migration.
        with self.repository.connection() as db:
            rows = db.execute('''SELECT * FROM journal_version WHERE fill_id IN ('''
                              + ','.join('?' for _ in fill_ids) + ') ORDER BY recorded_ms,note_id,version LIMIT 5001', fill_ids).fetchall()
        if len(rows) > 5000:
            raise AccountDataError('JOURNAL_QUERY_LIMIT')
        return [{'noteId': row['note_id'], 'version': row['version'], 'recordedMs': row['recorded_ms'],
                 'eventMs': row['event_ms'], 'fillId': row['fill_id'], 'payload': json.loads(row['payload'])} for row in rows]
