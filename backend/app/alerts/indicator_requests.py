"""Compatibility names mapped to public numeric definitions, without formulas."""
from app.data_engine.data_manager.models import SeriesKey
from app.indicator.query_contracts import BuiltinOutput, IndicatorQuery

ALIASES = {
    'rsi': BuiltinOutput('RSI', (('period', 14), ('source', 'close')), 'rsi'),
    'macdHist': BuiltinOutput('MACD', (('fast', 12), ('slow', 26), ('signal', 9), ('source', 'close')), 'hist'),
    'ma20': BuiltinOutput('MA', (('period', 20), ('source', 'close')), 'ma'),
}


def request_for(target, fields):
    return IndicatorQuery(SeriesKey(target['symbol'], target['interval'],
        exchange=target['exchange'], market_type=target['marketType']),
        tuple(ALIASES[field] for field in sorted(fields)), source_slots=250)


def values_from(snapshot):
    values = dict(snapshot.values)
    return {name: values.get(output) for name, output in ALIASES.items()}
