"""ADR-DATA-002 D3: consumers ask for a declared role, not an exchange name."""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.data_preparation.models import PreparationError
from app.exchanges import roles as capability_roles
from app.exchanges.contracts import validate_exchange_capabilities
from app.exchanges.models import (
    CapabilityRole,
    ExchangeCapabilities,
    ExchangeMarket,
    MarketChannel,
    MarketChannelCapability,
    serialize_exchange_capabilities,
)
from app.exchanges.roles import (
    BINANCE_USDM_AGG_TRADES_ARCHIVE,
    TRADES_HISTORY_ARCHIVE,
    venue_role,
    venue_role_contract,
)
from app.replay.history_archive import ReplayHistoryArchiveError
from app.replay.official_trade_history import OfficialTradeHistoryRepository
from app.replay.remote_trade_archive import sync_official_agg_trade_availability
from app.replay.trade_import import ReplayTradeImportError, require_official_trade_archive
from tests.test_trade_preparation import adapter_and_network, requirement


def _capabilities(exchange: str, *roles: CapabilityRole, markets=("spot", "futures")):
    return ExchangeCapabilities(
        exchange=exchange,
        name=exchange,
        capability_schema_version=3,
        markets=[ExchangeMarket(market, market, market) for market in markets],
        native_intervals=["1m"],
        channels=[MarketChannelCapability(
            channel=MarketChannel.KLINE, market_types=tuple(markets), history=True,
            history_transports=("rest_history",), params={"interval": ["1m"]},
        )],
        roles=list(roles),
    )


@pytest.fixture
def venues(monkeypatch):
    """Route role lookups to explicit capability documents."""

    documents: dict[str, ExchangeCapabilities] = {}
    original = capability_roles._venue_capabilities

    def lookup(exchange, registry):
        return documents[exchange] if exchange in documents else original(exchange, registry)

    monkeypatch.setattr(capability_roles, "_venue_capabilities", lookup)
    return documents


def test_role_declarations_are_normalised_and_need_a_contract():
    role = CapabilityRole(" Trades.History.Archive ", ("Futures", "futures"), " acme/1 ")
    assert (role.role, role.market_types, role.contract) == (
        "trades.history.archive", ("futures",), "acme/1")
    for name, contract in (("", "acme/1"), ("trades.history.archive", " ")):
        with pytest.raises(ValueError):
            CapabilityRole(name, ("futures",), contract)


def _role_issues(document):
    return {issue.code for issue in validate_exchange_capabilities(document).issues
            if issue.code.startswith("capabilities.role")}


def test_validation_rejects_unknown_markets_and_duplicates():
    good = _capabilities("acme", CapabilityRole(TRADES_HISTORY_ARCHIVE, ("futures",), "acme/1"))
    assert _role_issues(good) == set()
    unknown = _capabilities("acme", CapabilityRole(TRADES_HISTORY_ARCHIVE, ("option",), "acme/1"))
    duplicate = _capabilities(
        "acme",
        CapabilityRole(TRADES_HISTORY_ARCHIVE, ("futures",), "acme/1"),
        CapabilityRole(TRADES_HISTORY_ARCHIVE, ("futures",), "acme/2"),
    )
    assert _role_issues(unknown) == {"capabilities.role_market_unknown"}
    assert _role_issues(duplicate) == {"capabilities.role_duplicate"}


def test_roles_are_part_of_the_wire_document():
    document = _capabilities("acme", CapabilityRole(TRADES_HISTORY_ARCHIVE, ("futures",), "acme/1"))
    assert serialize_exchange_capabilities(document)["roles"] == [
        {"role": TRADES_HISTORY_ARCHIVE, "market_types": ["futures"], "contract": "acme/1"}]
    legacy = SimpleNamespace(to_dict=lambda: {"exchange": "old"})
    assert serialize_exchange_capabilities(legacy)["roles"] == []


def test_builtin_venues_declare_the_trade_archive_only_for_binance_usdm():
    assert venue_role_contract("binance", "futures", TRADES_HISTORY_ARCHIVE) == (
        BINANCE_USDM_AGG_TRADES_ARCHIVE)
    for exchange, market in (("binance", "spot"), ("okx", "futures"), ("okx", "spot"),
                             ("twelvedata", "stock"), ("binanceusdm", "swap.linear"), ("", "futures")):
        assert venue_role(exchange, market, TRADES_HISTORY_ARCHIVE) is None, (exchange, market)


def test_registered_venues_keep_the_same_roles():
    from app.exchanges.registry import bootstrap_default_adapters

    registry = bootstrap_default_adapters()
    registered = registry.capabilities_view("binance").to_dict()["roles"]
    assert registered == capability_roles._builtin_capabilities("binance").to_dict()["roles"]
    assert {"role": TRADES_HISTORY_ARCHIVE, "market_types": ["futures"],
            "contract": BINANCE_USDM_AGG_TRADES_ARCHIVE} in registered
    assert registry.capabilities_view("okx").to_dict()["roles"] == []
    assert venue_role_contract("binance", "futures", TRADES_HISTORY_ARCHIVE, registry=registry) == (
        BINANCE_USDM_AGG_TRADES_ARCHIVE)
    for exchange, market in (("okx", "futures"), ("binanceusdm", "swap.linear"),
                             ("binanceusdm", "futures"), ("bybit", "swap.linear"), ("twelvedata", "stock")):
        assert venue_role(exchange, market, TRADES_HISTORY_ARCHIVE, registry=registry) is None


def test_importer_follows_the_declared_archive(venues):
    assert require_official_trade_archive(" Binance ", "FUTURES") == "binance"
    for exchange, market in (("okx", "futures"), ("binance", "spot"), ("twelvedata", "stock")):
        with pytest.raises(ReplayTradeImportError, match="publishes no verified trade archive"):
            require_official_trade_archive(exchange, market)
    venues["acme"] = _capabilities(
        "acme", CapabilityRole(TRADES_HISTORY_ARCHIVE, ("futures",), "acme.trades/1"))
    with pytest.raises(ReplayTradeImportError, match="acme futures publishes no verified"):
        require_official_trade_archive("acme", "futures")
    venues["acme"] = _capabilities(
        "acme", CapabilityRole(TRADES_HISTORY_ARCHIVE, ("futures",), BINANCE_USDM_AGG_TRADES_ARCHIVE))
    assert require_official_trade_archive("acme", "futures") == "acme"


def test_availability_sync_refuses_venues_without_the_archive(tmp_path):
    def opener(*_args, **_kwargs):
        raise AssertionError("no request before the role check")

    with pytest.raises(ReplayHistoryArchiveError, match="okx futures publishes no verified trade archive"):
        sync_official_agg_trade_availability(
            tmp_path, exchange="okx", market_type="futures", symbol="BTCUSDT",
            as_of_date=date(2026, 11, 1), opener=opener)


def test_preparation_refuses_venues_without_the_archive(tmp_path, venues):
    adapter, _, calls = adapter_and_network(tmp_path)
    now = adapter.now_ms()
    for update in ({"exchange": "okx"}, {"market_type": "spot"},
                   {"exchange": "twelvedata", "market_type": "stock", "symbol": "AAPL"}):
        with pytest.raises(PreparationError) as failure:
            adapter.trades.validate(requirement().model_copy(update=update), now)
        assert failure.value.code == "TRADE_PROVIDER_UNSUPPORTED"
        assert "publishes no verified trade archive" in str(failure.value)
    adapter.trades.validate(requirement(), now)
    venues["acme"] = _capabilities(
        "acme", CapabilityRole(TRADES_HISTORY_ARCHIVE, ("futures",), BINANCE_USDM_AGG_TRADES_ARCHIVE))
    adapter.trades.validate(requirement().model_copy(update={"exchange": "acme"}), now)
    assert calls == []


def test_chart_history_lists_only_archive_series(tmp_path):
    identities = [
        {"exchange": "binance", "market_type": "futures", "symbol": "BTCUSDT"},
        {"exchange": "okx", "market_type": "futures", "symbol": "BTCUSDT"},
        {"exchange": "binance", "market_type": "spot", "symbol": "BTCUSDT"},
    ]
    window = SimpleNamespace(start_time_ms=0, end_time_ms=86_399_999)
    archive = SimpleNamespace(
        list_verified_identities=lambda: identities,
        selection_snapshot=lambda **identity: ("epoch-1", (window,)),
    )
    repository = OfficialTradeHistoryRepository(tmp_path, archive)
    listed = repository.list_all_series()
    assert len(listed) == 1
    assert "binance" in repr(listed[0]) and "futures" in repr(listed[0])


# D3b: replay training and preparation.

def test_binance_declares_the_replay_training_roles():
    from app.exchanges import roles

    expected = {
        (roles.BOOK_HISTORY, "futures"): roles.BINANCE_USDM_DIFF_DEPTH_CAPTURE,
        (roles.HEDGE_PUBLIC_HISTORY, "futures"): roles.BINANCE_USDM_HEDGE_PUBLIC_HISTORY,
        (roles.HISTORY_NATIVE_ARCHIVE, "spot"): roles.BINANCE_PUBLIC_KLINE_ARCHIVE,
        (roles.HISTORY_EARLIEST_PAGE, "spot"): roles.BINANCE_KLINES_START_TIME_ASCENDING,
        (roles.HISTORY_EARLIEST_PAGE, "futures"): roles.BINANCE_KLINES_START_TIME_ASCENDING,
    }
    for (role, market), contract in expected.items():
        assert venue_role_contract("binance", market, role) == contract
    for role, market in ((roles.BOOK_HISTORY, "spot"), (roles.HEDGE_PUBLIC_HISTORY, "spot"),
                         (roles.HISTORY_NATIVE_ARCHIVE, "futures")):
        assert venue_role("binance", market, role) is None
    for role, _market in expected:
        for exchange, market in (("okx", "futures"), ("okx", "spot"), ("twelvedata", "stock")):
            assert venue_role(exchange, market, role) is None


def test_training_setup_admission_asks_for_hedge_and_book_roles(venues):
    from app.exchanges import roles
    from app.replay.training.admission_rules import setup_market_compatibility

    def check(exchange, **settings):
        entry = {"identity": {"exchange": exchange, "market_type": "futures", "symbol": "BTCUSDT"}}
        return setup_market_compatibility(settings, entry, capability_admission={}, committed_start_ms=None)

    assert check("okx", position_mode="HEDGE")["code"] == "HEDGE_BINANCE_USDM_REQUIRED"
    assert check("okx", book_mode="BOOK_ASSISTED_REQUIRED")["code"] == "BOOK_BINANCE_USDM_REQUIRED"
    assert check("binance", position_mode="HEDGE").get("code") != "HEDGE_BINANCE_USDM_REQUIRED"
    assert check("binance", book_mode="BOOK_ASSISTED_REQUIRED")["code"] != "BOOK_BINANCE_USDM_REQUIRED"
    venues["acme"] = _capabilities(
        "acme",
        CapabilityRole(roles.HEDGE_PUBLIC_HISTORY, ("futures",), roles.BINANCE_USDM_HEDGE_PUBLIC_HISTORY),
        CapabilityRole(roles.BOOK_HISTORY, ("futures",), "acme.book/1"),
    )
    assert check("acme", position_mode="HEDGE").get("code") != "HEDGE_BINANCE_USDM_REQUIRED"
    assert check("acme", book_mode="BOOK_ASSISTED_REQUIRED")["code"] == "BOOK_BINANCE_USDM_REQUIRED"


def test_market_random_probes_the_listing_only_on_earliest_first_pages(monkeypatch, venues):
    import asyncio

    from app.exchanges import roles
    from tests.test_market_random import START, MINUTE, Factory, payload
    from app.data_preparation.market_random import resolve_market_random

    monkeypatch.setattr("app.data_preparation.market_random.get_cached_symbol_metadata", lambda *a: None)
    for exchange in ("okx", "twelvedata"):
        with pytest.raises(PreparationError, match="上市边界"):
            asyncio.run(resolve_market_random(
                payload().model_copy(update={"exchange": exchange}), Factory(), now_ms=START + 20 * MINUTE))
    venues["acme"] = _capabilities("acme", CapabilityRole(
        roles.HISTORY_EARLIEST_PAGE, ("spot",), roles.BINANCE_KLINES_START_TIME_ASCENDING))
    factory = Factory()
    setup = asyncio.run(resolve_market_random(
        payload().model_copy(update={"exchange": "acme"}), factory, now_ms=START + 20 * MINUTE,
        randbelow=lambda n: 0))
    assert setup["start_mode"] == "RANDOM" and factory.calls[0]["start_ms"] == 0


# D3c: strategies.

def test_continuous_futures_follow_declared_contract_rules(venues):
    from app.exchanges import roles

    assert venue_role_contract("binance", "futures", roles.CONTRACT_RULES) == roles.BINANCE_USDM_LINEAR_BASE_QUANTITY
    for exchange in ("okx", "twelvedata", "binanceusdm"):
        assert venue_role(exchange, "futures", roles.CONTRACT_RULES) is None


def test_continuous_definition_refuses_futures_without_contract_rules(venues):
    from app.backtest.continuous_definition import prepare_definition
    from app.backtest.errors import BacktestError
    from app.data_engine.data_manager.models import SeriesKey
    from app.exchanges import roles
    from tests.test_continuous_provider import spec

    def refused(exchange):
        try:
            prepare_definition(spec(), {}, SeriesKey("BTCUSDT", "1m", market_type="futures", exchange=exchange),
                               follow=True)
        except BacktestError as failure:
            return failure.code == "FIDELITY_UNSUPPORTED" and "contract rules" in str(failure)
        return False

    assert refused("okx")
    assert not refused("binance")
    venues["acme"] = _capabilities("acme", CapabilityRole(
        roles.CONTRACT_RULES, ("futures",), roles.BINANCE_USDM_LINEAR_BASE_QUANTITY))
    assert not refused("acme")


def test_pine_daily_risk_windows_follow_the_market_calendar():
    from app.backtest.errors import BacktestError
    from app.backtest.pine_risk_stops import UTC_24_7_WINDOW_POLICY, window_contract

    daily = {"strategy.risk.max_intraday_loss"}
    for exchange, market in (("binance", "spot"), ("binance", "usdm"), ("binance", "futures"), ("okx", "futures")):
        contract = window_contract({"exchange": exchange, "market_type": market, "interval": "1h"}, daily)
        assert contract["policy"] == UTC_24_7_WINDOW_POLICY == "BINANCE_UTC_24_7_V1"
    for exchange, market in (("twelvedata", "stock"), ("unknown", "spot"), ("binance", "option")):
        with pytest.raises(BacktestError, match="around the clock"):
            window_contract({"exchange": exchange, "market_type": market, "interval": "1h"}, daily)
    assert window_contract({"exchange": "twelvedata", "market_type": "stock"}, {"strategy.risk.allow_entry_in"}) == {
        "policy": "NON_WINDOWED_V1"}


def test_pine_ticker_naming_comes_from_the_venue_normalizer():
    from app.backtest.pine_ticker import venue_pine_ticker, venue_storage_symbol
    from app.indicator.pine_host_inputs import chart_pine_symbol

    assert venue_pine_ticker("binance", "futures", "BTCUSDT") == "BTCUSDT.P"
    assert venue_pine_ticker("binance", "usdm", "BTCUSDT.P") == "BTCUSDT.P"
    assert venue_pine_ticker("binance", "spot", "BTCUSDT") == "BTCUSDT"
    assert venue_storage_symbol("binance", "swap", "ETHUSDT.P") == "ETHUSDT"
    assert venue_storage_symbol("binance", "spot", "ETHUSDT.P") == "ETHUSDT.P"
    for exchange, market, symbol in (("okx", "futures", "BTC-USDT-SWAP"), ("twelvedata", "stock", "AAPL:NASDAQ")):
        assert venue_pine_ticker(exchange, market, symbol) == symbol
        assert venue_storage_symbol(exchange, market, symbol + ".P") == symbol + ".P"
    context = SimpleNamespace(exchange="binance", market_type="futures", symbol="BTCUSDT")
    assert chart_pine_symbol(context) == "BINANCE:BTCUSDT.P"
    assert chart_pine_symbol(SimpleNamespace(exchange="okx", market_type="futures", symbol="BTC-USDT-SWAP")) == (
        "OKX:BTC-USDT-SWAP")


def test_pine_engine_names_the_chart_through_the_venue():
    from app.backtest.strategy.pine_engine import PineEngineProvider

    engine = PineEngineProvider()
    try:
        for market, chart, expected in (
            ("usdm", "BINANCE:BTCUSDT", "BINANCE:BTCUSDT.P"),
            ("futures", "BINANCE:BTCUSDT.P", "BINANCE:BTCUSDT.P"),
            ("spot", "BINANCE:BTCUSDT", "BINANCE:BTCUSDT"),
            ("futures", "OKX:BTC-USDT-SWAP", "OKX:BTC-USDT-SWAP"),
            ("stock", "AAPL:NASDAQ", "AAPL:NASDAQ"),
            ("", "LOCAL:LOCAL", "LOCAL:LOCAL"),
        ):
            engine.context = {"pineChartMarketType": market}
            assert engine._pine_chart_symbol(chart) == expected, (market, chart)
    finally:
        engine.close()


def test_advanced_market_data_roles_are_declared_by_the_venues_that_supply_them():
    from app.exchanges import roles
    from app.exchanges.ccxt_ext.catalog import get_ccxt_catalog_entry
    from app.exchanges.ccxt_ext.generic import CcxtUnifiedPlugin

    expected = {
        roles.FUNDING_HYBRID_HISTORY: roles.BINANCE_PREMIUM_INDEX_CUMAVG,
        roles.FUNDING_SETTLEMENT_HISTORY: roles.BINANCE_USDM_REGULAR_SETTLEMENT,
        roles.OPEN_INTEREST_NATIVE_GRID: roles.BINANCE_OI_GRID,
    }
    for role, contract in expected.items():
        assert venue_role_contract("binance", "futures", role) == contract
        assert venue_role("binance", "spot", role) is None
        # OKX's funding and OI history come from CCXT channels, without a role.
        assert venue_role("okx", "futures", role) is None

    gate = CcxtUnifiedPlugin(get_ccxt_catalog_entry("gate")).capabilities()
    assert [(item.role, item.market_types, item.contract) for item in gate.roles] == [
        (roles.OPEN_INTEREST_NATIVE_GRID, ("swap.linear", "swap.inverse"), roles.GATE_OI_GRID)]
    assert _role_issues(gate) == set()
    okx = CcxtUnifiedPlugin(get_ccxt_catalog_entry("okx")).capabilities()
    assert okx.roles == []


def _route_history(monkeypatch, tmp_path, document, channel, *, market_type="futures", **kwargs):
    """Which bounded history path the market data service takes for ``document``."""
    import asyncio

    from app.data_engine.market_data.models import MarketStreamKey
    from app.data_engine.market_data.service import MarketDataService
    from app.data_engine.storage.market_metrics_repo import MarketMetricsRepository

    service = MarketDataService(
        SimpleNamespace(), metrics_repository=MarketMetricsRepository(tmp_path / "metrics.sqlite"))
    monkeypatch.setattr(MarketDataService, "_validate_key", staticmethod(lambda key, *, history: document))
    monkeypatch.setattr(service, "_history_refresh_plan", lambda key, **_: None)

    async def settlement(*_, **__):
        return ("settlement", None)

    async def grid(*_, revision, **__):
        return ("grid", revision)

    async def hybrid(*_, **__):
        return ("hybrid", None)

    monkeypatch.setattr(service, "_sparse_funding_history_page", settlement)
    monkeypatch.setattr(service, "_shared_oi_history", grid)
    monkeypatch.setattr(service, "_hybrid_funding_history_page", hybrid)
    key = MarketStreamKey.build(document.exchange, market_type, "BTCUSDT", channel)

    async def read():
        try:
            return await service.history_page(key, start_ms=0, end_ms=3_000_000, **kwargs)
        finally:
            await service.shutdown()

    return asyncio.run(read())


def test_market_history_paths_follow_the_declared_roles(monkeypatch, tmp_path):
    from app.data_engine.market_data.models import MarketChannel as Channel
    from app.exchanges import roles

    declared = _capabilities(
        "okx",
        CapabilityRole(roles.FUNDING_HYBRID_HISTORY, ("futures",), roles.BINANCE_PREMIUM_INDEX_CUMAVG),
        CapabilityRole(roles.FUNDING_SETTLEMENT_HISTORY, ("futures",), roles.BINANCE_USDM_REGULAR_SETTLEMENT),
        CapabilityRole(roles.OPEN_INTEREST_NATIVE_GRID, ("futures",), roles.BINANCE_OI_GRID),
    )
    route = lambda document, channel, **kw: _route_history(monkeypatch, tmp_path, document, channel, **kw)
    assert route(declared, Channel.FUNDING_RATE, view="hybrid", period="1h") == ("hybrid", None)
    assert route(declared, Channel.FUNDING_RATE, mode="fill_missing") == ("settlement", None)
    assert route(declared, Channel.OPEN_INTEREST, period="15m", mode="fill_missing") == (
        "grid", roles.BINANCE_OI_GRID)

    undeclared = _capabilities("okx")
    with pytest.raises(ValueError, match="premium index funding formula"):
        route(undeclared, Channel.FUNDING_RATE, view="hybrid", period="1h")
    for channel, period in ((Channel.FUNDING_RATE, None), (Channel.OPEN_INTEREST, "15m")):
        with pytest.raises(ValueError, match="verified funding or OI policy"):
            route(undeclared, channel, period=period, mode="fill_missing")

    # A contract the service does not implement is the same as no role.
    unknown = _capabilities(
        "okx", CapabilityRole(roles.FUNDING_HYBRID_HISTORY, ("futures",), "acme-funding/1"))
    with pytest.raises(ValueError, match="premium index funding formula"):
        route(unknown, Channel.FUNDING_RATE, view="hybrid", period="1h")

    # Gate's grid covers only 5m samples.
    gate = _capabilities(
        "gate", CapabilityRole(roles.OPEN_INTEREST_NATIVE_GRID, ("swap.linear",), roles.GATE_OI_GRID),
        markets=("swap.linear",))
    assert route(gate, Channel.OPEN_INTEREST, market_type="swap.linear", period="5m", mode="fill_missing") == (
        "grid", roles.GATE_OI_GRID)
    with pytest.raises(ValueError, match="verified funding or OI policy"):
        route(gate, Channel.OPEN_INTEREST, market_type="swap.linear", period="15m", mode="fill_missing")
