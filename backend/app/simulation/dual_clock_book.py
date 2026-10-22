"""Physical book updates for a print-driven chart, without extra Pine ticks."""
from decimal import Decimal, InvalidOperation

from app.market_dataset.snapshot import MarketDatasetError
from .book_kernel import BookAssistedKernel
from .depth_kernel import DepthQueueKernel
from .sampled_book_kernel import SampledBookKernel
from .trade_kernel import TradeSimulationKernel

BOOK_MODES = {'BOOK_ASSISTED', 'BOOK_DEPTH', 'BOOK_SAMPLED'}


def execution_type(mode):
    kinds = {'AGG_TRADE_EXECUTION': TradeSimulationKernel,
             'BOOK_ASSISTED': BookAssistedKernel,
             'BOOK_DEPTH': DepthQueueKernel, 'BOOK_SAMPLED': SampledBookKernel}
    try:
        return kinds[mode]
    except KeyError:
        raise MarketDatasetError('unsupported chart execution fidelity', code='FIDELITY_UNSUPPORTED') from None


def validate_assisted_quote(payload, previous):
    sequence = payload.get('book_sequence')
    if type(sequence) is not int or sequence < 0:
        raise MarketDatasetError('invalid book sequence', code='DATA_QUALITY_FAILED')
    if previous is None and payload.get('snapshot') is not True:
        raise MarketDatasetError('initial book snapshot is required', code='DATA_ROLE_MISSING')
    if previous is not None and (sequence != previous + 1 or payload.get('reset')):
        raise MarketDatasetError('book continuity changed', code='DATA_GAP_REJECTED')
    try:
        bid, ask = Decimal(str(payload.get('bid'))), Decimal(str(payload.get('ask')))
    except InvalidOperation:
        raise MarketDatasetError('invalid book quote', code='DATA_QUALITY_FAILED') from None
    if not bid.is_finite() or not ask.is_finite() or bid <= 0 or ask < bid:
        raise MarketDatasetError('book must be positive and uncrossed', code='DATA_QUALITY_FAILED')
    return sequence


def apply_quote(dual, event):
    if dual.execution_fidelity not in BOOK_MODES:
        raise MarketDatasetError('book update requires a physical book kernel', code='FIDELITY_MISLABEL')
    if dual.execution_fidelity == 'BOOK_ASSISTED':
        sequence=validate_assisted_quote(event.payload,dual._last_book_sequence)
        dual.execution._match(event)
        dual._last_book_sequence = sequence
    else:
        # Depth/sample kernels own their continuity, consumed liquidity and
        # same-millisecond sample eligibility, including checkpoint restoration.
        dual.execution._match(event)


def report_identity(mode):
    if mode == 'AGG_TRADE_EXECUTION':
        return dict(fidelity_mode=mode, source_event_kind='AGG_TRADE',
                    report_label='AGGREGATED_TRADE_SEQUENCE')
    return dict(fidelity_mode=mode, source_event_kind='TRADE_AND_L2',
                report_label=mode, queue_exact=False)
