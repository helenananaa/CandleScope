import json

import pytest

from app.exchanges.ccxt_ext import catalog


@pytest.fixture
def fresh_catalog(monkeypatch):
    monkeypatch.delenv(catalog.PRECOMPUTED_CATALOG_ENV, raising=False)
    catalog.get_ccxt_catalog.cache_clear()
    yield
    catalog.get_ccxt_catalog.cache_clear()


def test_precomputed_catalog_matches_the_computed_catalog(tmp_path, monkeypatch, fresh_catalog):
    computed = catalog.get_ccxt_catalog()
    document = tmp_path / "ccxt_catalog.json"
    document.write_text(json.dumps(catalog.ccxt_catalog_document(computed)), encoding="utf-8")

    monkeypatch.setenv(catalog.PRECOMPUTED_CATALOG_ENV, str(document))
    catalog.get_ccxt_catalog.cache_clear()

    assert catalog.get_ccxt_catalog() == computed
    assert catalog.get_ccxt_catalog_entry("binance") == next(
        entry for entry in computed if entry.exchange_id == "binance"
    )


def test_precomputed_catalog_rejects_another_ccxt_version(tmp_path, monkeypatch, fresh_catalog):
    document = tmp_path / "ccxt_catalog.json"
    document.write_text(json.dumps({"ccxt_version": "0.0.1", "entries": []}), encoding="utf-8")
    monkeypatch.setenv(catalog.PRECOMPUTED_CATALOG_ENV, str(document))

    with pytest.raises(RuntimeError, match="0.0.1"):
        catalog.get_ccxt_catalog()
