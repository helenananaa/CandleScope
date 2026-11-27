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
    assert registry.capabilities_view("binance").to_dict()["roles"] == [{
        "role": TRADES_HISTORY_ARCHIVE, "market_types": ["futures"],
        "contract": BINANCE_USDM_AGG_TRADES_ARCHIVE}]
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
