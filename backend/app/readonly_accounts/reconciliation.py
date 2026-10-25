"""Conservative, reproducible reconciliation. Source facts are never rewritten.

All amounts remain decimal strings. Attribution requires a unique exposure and
agreement with OKX's closed-position totals; missing evidence is never zero.
"""
from __future__ import annotations

import time
from collections import defaultdict
from decimal import Decimal, localcontext

from .normalization import AccountDataError, decimal, exact, timestamp
from .sync import uncovered_ranges

ZERO = Decimal(0)
LIMIT = 500
BOUNDARY_MS = 5000


def number(row, key):
    return decimal(row.get(key))


def covered(data, kind, start, end):
    ranges = [row for row in data['coverage'] if row['kind'] == kind]
    return not uncovered_ranges(start, end, ranges)


def totals(rows, key):
    return sum((number(row, key) for row in rows), ZERO)


def status(issues):
    return 'matched' if not issues else 'partial'


def fee_check(data, fills, bills):
    by_id = {item['value']['billId']: item for item in bills}
    checked, issues = 0, []
    for item in fills:
        fill = item['value']
        bill = by_id.get(fill['fillId'])
        try:
            if bill is None:
                raise AccountDataError('missingBill')
            raw = bill['raw']
            if (raw.get('type') != '2' or raw.get('instId') != fill['instrument']
                    or raw.get('ordId') != fill['orderId'] or raw.get('tradeId') != fill['tradeId']
                    or raw.get('ccy') != fill['feeCurrency']
                    or (item['raw'].get('mgnMode') and raw.get('mgnMode') != item['raw']['mgnMode'])):
                raise AccountDataError('identityMismatch')
            if number(raw, 'fee') != number(fill, 'feeCashChange') or number(raw, 'pnl') != number(fill, 'exchangeRealizedPnl'):
                raise AccountDataError('amountMismatch')
            # Isolated collateral moves between account and position balances.
            # It is not an expense or realized P&L.
            collateral = number(raw, 'posBalChg') if raw.get('mgnMode') == 'isolated' else ZERO
            if number(raw, 'balChg') + collateral != number(raw, 'pnl') + number(raw, 'fee'):
                raise AccountDataError('amountMismatch')
            checked += 1
        except AccountDataError as exc:
            issues.append({'id': fill['fillId'], 'reason': exc.code if exc.code in {'missingBill','identityMismatch','amountMismatch'} else 'missingAmount'})
    fill_ids = {item['value']['fillId'] for item in fills}
    for item in bills:
        bill = item['value']
        if bill['category'] == 'trade' and bill['inSelectedScope'] and bill['billId'] not in fill_ids:
            issues.append({'id': bill['billId'], 'reason': 'missingFill'})
    return {'status': status(issues) if fills else 'partial', 'checked': checked,
            'total': len(fills), 'issues': issues[:LIMIT], 'issueCount': len(issues)}


def cash_check(data, bills):
    groups = defaultdict(list)
    for item in bills:
        groups[item['value']['currency']].append(item['raw'])
    snapshot = data['snapshots'].get('balances', {})
    balances = {row['ccy']: row for account in snapshot.get('data', []) for row in account.get('details', [])}
    result = []
    for currency in sorted(set(groups) | set(balances)):
        rows = groups[currency]
        output = {'currency': currency, 'status': 'partial', 'count': len(rows), 'breaks': 0,
                  'openingDerived': None, 'change': None, 'closing': None, 'snapshot': None,
                  'difference': None, 'tolerance': '0.000000000001', 'reason': 'missingBills', 'snapshotMs': snapshot.get('receivedMs')}
        try:
            if currency in balances:
                output['snapshot'] = exact(number(balances[currency], 'cashBal'))
            if not rows:
                result.append(output)
                continue
            # OKX bill IDs are numeric, including when timestamps tie.
            if any(not str(row['billId']).isdigit() for row in rows):
                raise AccountDataError('ambiguousOrder')
            rows.sort(key=lambda row: (timestamp(row['ts']), int(row['billId'])))
            opening = number(rows[0], 'bal') - number(rows[0], 'balChg')
            previous = opening
            for row in rows:
                balance, change = number(row, 'bal'), number(row, 'balChg')
                if previous + change != balance:
                    output['breaks'] += 1
                previous = balance
            output.update(openingDerived=exact(opening), change=exact(totals(rows, 'balChg')), closing=exact(previous))
            if output['snapshot'] is None:
                output['reason'] = 'missingSnapshot'
            else:
                difference = decimal(output['snapshot']) - previous
                output['difference'] = exact(difference)
                enough = covered(data, 'bills', timestamp(rows[0]['ts']), timestamp(rows[-1]['ts']))
                # Snapshot and ledger are independent reads. A difference is
                # displayed, not silently dismissed as a timing race.
                output['reason'] = 'cashDifference' if abs(difference) > decimal(output['tolerance']) or output['breaks'] else 'coverageGap' if not enough else None
                output['status'] = 'matched' if output['reason'] is None else 'partial'
        except (AccountDataError, KeyError):
            output['reason'] = 'missingAmount'
        result.append(output)
    return result


def fill_margin_mode(item, bills_by_id):
    # fills-history omits mgnMode. An exactly linked trade bill provides it;
    # never infer cross/isolated from the current account configuration.
    fill, raw = item['value'], item['raw']
    explicit = raw.get('mgnMode')
    if explicit in {'cross', 'isolated'}:
        return explicit
    bill = bills_by_id.get(fill['fillId'], {}).get('raw', {})
    if (bill.get('type') == '2' and bill.get('instId') == fill['instrument']
            and bill.get('ordId') == fill['orderId'] and bill.get('tradeId') == fill['tradeId']
            and bill.get('ccy') == fill['feeCurrency'] and bill.get('mgnMode') in {'cross', 'isolated'}):
        return bill['mgnMode']
    return None


def position_check(data, fills, bills, now):
    snapshot = data['snapshots'].get('position_history', {})
    history = snapshot.get('data', {})
    state = data['snapshots'].get('position_history_state', {}).get('data', {})
    fresh = (history.get('complete') is True and state.get('complete') is True
             and 0 <= now - snapshot.get('receivedMs', 0) <= 300_000)
    histories = history.get('rows', [])
    groups = defaultdict(list)
    bills_by_id = {item['value']['billId']: item for item in bills}
    for item in fills:
        f = item['value']
        groups[(f['instrument'], f['positionSide'], fill_margin_mode(item, bills_by_id))].append(f)
    cycles, used = [], set()
    instruments = {item['value']['instrument'] for item in fills} | {item['value']['instrument'] for item in bills if item['value']['inSelectedScope']}
    for h in histories:
        key = (h.get('instId'), h.get('posSide'), h.get('mgnMode'))
        if key[0] not in instruments or key[1] not in {'long', 'short'}:
            continue
        cycle = {'id': str(h.get('posId', '')), 'instrument': key[0], 'positionSide': key[1],
                 'marginMode': key[2], 'currency': str(h.get('ccy', '')), 'status': 'partial',
                 'reason': None, 'startMs': None, 'endMs': None, 'fillCount': 0,
                 'computedPnl': None, 'exchangePnl': None, 'pnlDifference': None,
                 'tolerance': None, 'fee': None, 'funding': None, 'net': None,
                 'fundingCount': 0, '_history': h, '_fills': [], '_eligible': False, '_funding': [], '_pendingFunding': False}
        cycles.append(cycle)
        try:
            start, end = timestamp(h.get('cTime')), timestamp(h.get('uTime'))
            cycle.update(startMs=start, endMs=end)
            selected = sorted((f for f in groups[key] if start-BOUNDARY_MS <= f['eventTimeMs'] <= end+BOUNDARY_MS), key=lambda f: f['eventTimeMs'])
            cycle['_fills'] = selected
            cycle['fillCount'] = len(selected)
            if not fresh:
                raise AccountDataError('historyUnavailable')
            if h.get('instType') != 'SWAP' or h.get('type') != '2' or h.get('mgnMode') not in {'cross', 'isolated'}:
                raise AccountDataError('unsupportedPosition')
            if not selected or abs(selected[0]['eventTimeMs']-start) > BOUNDARY_MS or abs(selected[-1]['eventTimeMs']-end) > BOUNDARY_MS:
                raise AccountDataError('openingUnknown')
            if not covered(data, 'fills', start, end) or not covered(data, 'bills', start, end):
                raise AccountDataError('coverageGap')
            if any(number(h, field) != ZERO for field in ['liqPenalty']):
                raise AccountDataError('unsupportedPosition')
            if h.get('settledPnl') not in (None, '', '0'):
                raise AccountDataError('unsupportedPosition')
            contract = selected[0]['contract']
            if any(f['contract'] != contract or f['feeCurrency'] != h.get('ccy') or f['settleCurrency'] != h.get('ccy') for f in selected):
                raise AccountDataError('currencyMismatch')
            # Opposite effects sharing a timestamp cannot be safely sequenced.
            effects = defaultdict(set)
            for f in selected:
                effects[f['eventTimeMs']].add(f['effect'])
            if any(len(effect) > 1 for effect in effects.values()):
                raise AccountDataError('ambiguousOrder')
            qty = basis = pnl = closed = ZERO
            for index, f in enumerate(selected):
                q, price = number(f, 'contracts'), number(f, 'price')
                if f['effect'] == 'open':
                    basis += q * (price if contract['kind'] == 'linear' else 1/price)
                    qty += q
                elif f['effect'] == 'close' and ZERO < q <= qty:
                    average = basis / qty
                    pnl += q * decimal(contract['contractValue']) * (price-average if contract['kind'] == 'linear' else average-1/price) * (1 if key[1] == 'long' else -1)
                    basis -= average*q
                    qty -= q
                    closed += q
                    if qty == ZERO and index != len(selected)-1:
                        raise AccountDataError('ambiguousHistory')
                else:
                    raise AccountDataError('openingUnknown')
            if qty or closed != number(h, 'closeTotalPos'):
                raise AccountDataError('openingUnknown')
            fee, fill_pnl = totals(selected, 'feeCashChange'), totals(selected, 'exchangeRealizedPnl')
            exchange_pnl, funding = number(h, 'pnl'), number(h, 'fundingFee')
            # Explicit conservative rounding allowance, per fill, in settlement
            # units. The actual difference is always returned to the user.
            tolerance = Decimal('0.00000001' if contract['kind'] == 'linear' else '0.000000000001') * len(selected)
            cycle.update(computedPnl=exact(pnl), exchangePnl=exact(exchange_pnl), pnlDifference=exact(pnl-exchange_pnl),
                         tolerance=exact(tolerance), fee=exact(fee), funding=exact(funding), net=exact(number(h, 'realizedPnl')))
            if (abs(pnl-exchange_pnl) > tolerance or abs(pnl-fill_pnl) > tolerance
                    or fee != number(h, 'fee') or abs(number(h, 'realizedPnl') - (exchange_pnl+fee+funding)) > tolerance):
                raise AccountDataError('amountMismatch')
            cycle['_eligible'] = True
        except (AccountDataError, KeyError, ZeroDivisionError) as exc:
            code = exc.code if isinstance(exc, AccountDataError) else ''
            cycle['reason'] = code if code in REASONS else 'missingAmount'
    # Reject overlapping histories, including reused position IDs and multiple
    # cumulative snapshots of a lifecycle. Never count the same fill twice.
    owners = defaultdict(list)
    for c in cycles:
        for f in c['_fills']:
            owners[f['fillId']].append(c)
    for matches in owners.values():
        if len(matches) > 1:
            for c in matches:
                c['_eligible'] = False
                c['reason'] = 'ambiguousHistory'
    funding_rows = []
    for item in bills:
        b, raw = item['value'], item['raw']
        if b['category'] != 'funding' or not b['inSelectedScope']:
            continue
        row = {'billId': b['billId'], 'instrument': b['instrument'], 'currency': b['currency'],
               'eventTimeMs': b['eventTimeMs'], 'amount': b['cashChange'], 'positionSide': None,
               'positionId': None, 'reason': 'noUniquePosition'}
        funding_rows.append(row)
        candidates = []
        try:
            for c in cycles:
                if (c['instrument'] != b['instrument'] or c['currency'] != b['currency']
                        or c['marginMode'] != raw.get('mgnMode') or c['startMs'] is None
                        or not c['startMs'] <= b['eventTimeMs'] <= c['endMs']):
                    continue
                candidates.append(c)
            # Every potentially matching leg is considered, even if its own
            # history is incomplete. Equal-size hedged positions stay unassigned.
            matching = []
            for c in candidates:
                if any(abs(f['eventTimeMs']-b['eventTimeMs']) <= BOUNDARY_MS for f in c['_fills']):
                    raise AccountDataError('settlementBoundary')
                qty = sum((number(f, 'contracts') * (1 if f['effect'] == 'open' else -1)
                           for f in c['_fills'] if f['eventTimeMs'] < b['eventTimeMs']), ZERO)
                if qty == number(raw, 'sz') and qty > ZERO:
                    matching.append(c)
                elif not c['_eligible']:
                    raise AccountDataError('noUniquePosition')
            if len(matching) != 1 or not matching[0]['_eligible']:
                raise AccountDataError('noUniquePosition')
            if raw.get('subType') not in {'173', '174'} or number(raw, 'pnl') != number(b, 'cashChange'):
                raise AccountDataError('amountMismatch')
            matching[0]['_funding'].append(row)
        except AccountDataError as exc:
            for c in candidates:
                c['_pendingFunding'] = True
            row['reason'] = exc.code if exc.code in REASONS else 'missingAmount'
    for c in cycles:
        if not c['_eligible']:
            continue
        found = sum((decimal(row['amount']) for row in c['_funding']), ZERO)
        if c['_pendingFunding'] or found != decimal(c['funding']):
            c['reason'] = 'fundingDifference'
            for row in c['_funding']:
                row['reason'] = 'fundingDifference'
            continue
        c['status'], c['reason'] = 'matched', None
        c['fundingCount'] = len(c['_funding'])
        used.update(f['fillId'] for f in c['_fills'])
        for row in c['_funding']:
            row.update(positionSide=c['positionSide'], positionId=c['id'], reason=None)
    clean = [{key: value for key, value in c.items() if not key.startswith('_')} for c in cycles]
    return clean, funding_rows, len(fills)-len(used), fresh


REASONS = frozenset({'historyUnavailable', 'unsupportedPosition', 'openingUnknown', 'coverageGap',
    'currencyMismatch', 'ambiguousOrder', 'ambiguousHistory', 'amountMismatch', 'missingAmount',
    'noUniquePosition', 'settlementBoundary', 'fundingDifference', 'missingBill', 'missingFill',
    'identityMismatch', 'cashDifference', 'missingBills', 'missingSnapshot'})


def reconcile_account(data, *, now_ms=None):
    now = int(time.time()*1000) if now_ms is None else now_ms
    fills = [item for item in data['facts'] if item['kind'] == 'fills']
    bills = [item for item in data['facts'] if item['kind'] == 'bills']
    with localcontext() as context:
        context.prec = 80
        fees = fee_check(data, fills, bills)
        cash = cash_check(data, bills)
        positions, funding, unmatched, history_ready = position_check(data, fills, bills, now)
    assigned = sum(row['positionSide'] is not None for row in funding)
    matched = sum(row['status'] == 'matched' for row in positions)
    account = data.get('account') or {}
    latest = account.get('last_success_ms')
    current = account.get('status') == 'synced' and latest is not None and 0 <= now-latest <= 300_000
    complete = (current and history_ready and fills and fees['status'] == 'matched' and cash
                and all(row['status'] == 'matched' for row in cash) and unmatched == 0 and assigned == len(funding))
    return {'schemaVersion': 1, 'status': 'matched' if complete else 'partial', 'generatedMs': now,
            'lastReadMs': latest, 'historyReady': history_ready, 'current': current,
            'fees': fees, 'cash': cash[:LIMIT], 'positions': positions[:LIMIT], 'funding': funding[:LIMIT],
            'counts': {'positions': len(positions), 'matchedPositions': matched, 'unmatchedFills': unmatched,
                       'funding': len(funding), 'assignedFunding': assigned, 'cash': len(cash)},
            'truncated': any(len(rows)>LIMIT for rows in [cash, positions, funding]) or fees['issueCount']>LIMIT,
            'contractKinds': sorted({item['value']['contract']['kind'] for item in fills})}
