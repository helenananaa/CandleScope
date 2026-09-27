from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

from scripts.check_architecture import dependencies, dependency_graph, dependency_path, violations

BACKEND = Path(__file__).resolve().parents[1]


def test_business_packages_do_not_depend_on_http_composition():
    assert violations(BACKEND / "app") == []


@pytest.mark.parametrize("source", [
    "import app.api.v1.symbols",
    "from app.api.v1.symbols import get_exchange_info",
    "from app import api",
    "from ..api.v1 import symbols",
    "from .. import api",
    "def delayed():\n    from app.api.v1 import symbols",
    "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from app.api import v1",
    "import importlib\nimportlib.import_module('app.api.v1.symbols')",
    "import importlib as loader\nloader.import_module('app.api.v1.symbols')",
    "from importlib import import_module as load\nload('..api.v1.symbols', __package__)",
    "from importlib import import_module\nimport_module('..api.v1.symbols', package='app.service')",
    "from importlib import import_module\nROUTE = 'app.api.' + 'v1.symbols'\nimport_module(ROUTE)",
    "__import__('app.api.v1.symbols')",
    "from builtins import __import__ as load\nload('app.api.v1.symbols')",
    "from app.main import app",
])
def test_gate_rejects_reverse_import_forms(tmp_path, source):
    app = tmp_path / "app"
    service = app / "service"
    service.mkdir(parents=True)
    (service / "worker.py").write_text(source, encoding="utf-8")
    assert violations(app)


def test_package_initializers_and_reexports_do_not_conceal_http(tmp_path):
    app = tmp_path / "app"
    for directory in (app / "service", app / "shared"):
        directory.mkdir(parents=True)
    (app / "service/worker.py").write_text("from app.shared.contracts import Request", encoding="utf-8")
    (app / "shared/contracts.py").write_text("class Request: pass", encoding="utf-8")
    (app / "shared/__init__.py").write_text("from app.api.v1 import symbols", encoding="utf-8")
    path = dependency_path(dependency_graph(app), "app.service.worker", ("app.api",))
    assert path == ["app.service.worker", "app.shared.contracts", "app.shared", "app.api.v1"]
    assert violations(app)


def test_shared_contract_cannot_hide_framework_behind_helper(tmp_path):
    app = tmp_path / "app"
    (app / "backtest").mkdir(parents=True)
    (app / "backtest/request_contracts.py").write_text("from .helper import Request", encoding="utf-8")
    (app / "backtest/helper.py").write_text("from fastapi import Request", encoding="utf-8")
    assert any("shared business owner depends on HTTP" in error for error in violations(app))


def test_only_composition_root_and_http_tree_can_import_routes(tmp_path):
    app = tmp_path / "app"
    (app / "api").mkdir(parents=True)
    (app / "main.py").write_text("from app.api import router", encoding="utf-8")
    (app / "api/routes.py").write_text("from . import router", encoding="utf-8")
    assert violations(app) == []
    # Comments, plain strings and unrelated import_module methods are not imports.
    assert dependencies("# from app.api import v1\ntext = 'app.api'\nstore.import_module('app.api')", "app.worker") == []


def test_business_imports_and_lazy_launch_paths_work_without_http():
    program = textwrap.dedent('''
        import asyncio
        import importlib.abc
        import sys
        from types import SimpleNamespace as NS

        class NoHTTP(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if any(fullname == name or fullname.startswith(name + ".")
                       for name in ("app.api", "app.main", "fastapi", "starlette")):
                    raise AssertionError("Business path attempted HTTP import: " + fullname)

        sys.meta_path.insert(0, NoHTTP())
        from app.backtest import request_contracts, native_contracts, snapshot_validation
        from app.replay import request_contracts as replay_contracts
        from app.exchanges import symbol_catalog, discovery_catalog
        from app.data_engine.market_data.order_book_contract import serialize_record
        from app.data_engine.history.exchange_policy import ExchangeHistoryPolicyResolver
        from app.data_preparation.bar_adapter import BarPreparationAdapter
        from app.data_preparation import native_plan, strategy_launcher
        from app.data_preparation.models import PreparationError
        from app.plugin_market_v2.data_manager_port import DataManagerConsumerPort

        adapter = BarPreparationAdapter.__new__(BarPreparationAdapter)
        adapter.local_data = object()
        try:
            adapter.validate(NS(progressive=False, consumer="STRATEGY", requirements=(),
                                intent={"replay_setup": {"unknown": True}}))
        except PreparationError as error:
            assert error.code == "INVALID_REPLAY_SETUP"
        else:
            raise AssertionError("Invalid setup was accepted")

        prior = {"run_id": "existing"}
        runtime = NS(service=NS(repository=NS(get_run_by_idempotency=lambda key: prior)))
        assert strategy_launcher.launch(runtime, {}, {}, "job") == prior
        runtime = NS(native=NS(create=lambda payload, key: (payload, key)))
        payload, key = native_plan.launch(runtime,
            {"language": "pine", "source": "plot(close)", "parameters": {}, "libraries": {}},
            [{"dataset_id": "dataset", "data_epoch": "epoch-123", "snapshot_hash": "hash-123",
              "start_time_ms": 0, "end_time_ms": 60000, "interval": "1m", "exchange": "binance",
              "market_type": "spot", "symbol": "BTCUSDT", "timeframe": "1"}], "job")
        assert key == "preparation:job" and payload["context"]["symbol"] == "BTCUSDT"

        symbol_catalog._symbol_cache[("test", "spot")] = [
            {"symbol": "BTCUSDT", "exchange": "test", "marketType": "spot", "active": True}]
        resolver = ExchangeHistoryPolicyResolver(None)
        assert resolver._lookup_symbol(NS(exchange="test", market_type="spot", symbol="BTCUSDT"))["symbol"] == "BTCUSDT"
        port = DataManagerConsumerPort(None)
        rows, _ = asyncio.run(port.list_symbols(NS(context=NS(exchange="test", market_type="spot"))))
        assert len(rows) == 1
        assert serialize_record(NS(to_dict=lambda: {"data": {"bids": [[100, 1]], "asks": [[101, 2]]}}))["data"]["bids"] == [[100.0, 1.0]]
        assert not any(name == "app.api" or name.startswith("app.api.") for name in sys.modules)
    ''')
    # Match the repository SDK paths pinned by conftest, but start with a fresh
    # module cache so prior HTTP tests cannot conceal initialization dependencies.
    environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
                   "PYTHONPATH": os.pathsep.join(sys.path)}
    result = subprocess.run([sys.executable, "-B", "-c", program], cwd=BACKEND,
                            env=environment, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
