from __future__ import annotations

from typing import Any

import asyncio

import pytest

from app.api.v1 import indicators as indicators_api
from app.api.v1 import stream_pyne_subscriptions as stream_subscriptions
from app.data_engine.data_manager.models import DataEventType
from app.indicator.custom_store import CustomIndicatorStore
from app.indicator.runtimes import PINE_COMPAT_RUNTIME_ID
from app.indicator.runtimes import pine_compat_adapter as pine_adapter


def _analysis(*features: str) -> dict[str, Any]:
    return {
        "schemaVersion": 3,
        "languageVersion": 6,
        "diagnostics": [],
        "compatibility": {
            "supported": [
                {"feature": feature, "span": {"line": 2, "column": 1}}
                for feature in features
            ],
            "unsupported": [],
        },
        "executable": True,
        "inputs": [{"callSiteId": 1, "name": "input.int", "title": "Length"}],
    }


def _runtime_output(**updates: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schemaVersion": 7,
        "plots": [{"id": 2, "values": [None, 2.0, 3.0]}],
        "plotChars": [],
        "plotShapes": [],
        "plotArrows": [],
        "plotBars": [],
        "plotCandles": [],
        "bgColors": [],
        "barColors": [],
        "hlines": [],
        "fills": [],
        "labels": [],
        "lines": [],
        "lineFills": [],
        "polylines": [],
        "boxes": [],
        "tables": [],
        "alerts": [],
        "diagnostics": [],
    }
    value.update(updates)
    return value


def _bars() -> list[dict[str, Any]]:
    return [
        {
            "time": 1_700_000_000 + index * 60,
            "open": 1.0 + index,
            "high": 2.0 + index,
            "low": 0.5 + index,
            "close": 1.5 + index,
            "volume": 10.0,
        }
        for index in range(3)
    ]


class _FakePineModule:
    def __init__(self, analysis: dict[str, Any], output: dict[str, Any]) -> None:
        self.analysis = analysis
        self.output = output
        self.run_calls: list[tuple[str, list[dict[str, Any]], dict[int, Any]]] = []

    def analyze_script(self, script: str) -> dict[str, Any]:
        assert script
        return self.analysis

    def run_script(
        self,
        script: str,
        bars: list[dict[str, Any]],
        *,
        input_overrides: dict[int, Any],
    ) -> dict[str, Any]:
        self.run_calls.append((script, bars, input_overrides))
        return self.output


def test_pine_adapter_normalizes_seconds_and_runtime_output(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _FakePineModule(
        _analysis("indicator", "input.int", "ta.sma", "plot"),
        _runtime_output(),
    )
    monkeypatch.setattr(pine_adapter, "_load_module", lambda: module)

    result = pine_adapter.execute_pine_script(
        script='//@version=6\nindicator("SMA", overlay=true)\nplot(close)',
        ohlcv=_bars(),
        params={"1": 2},
        executor_mode="inline",
    )

    assert result.ok is True
    assert result.lines[0]["id"] == "pine-plot-2"
    assert result.lines[0]["pane"] == "main"
    assert result.lines[0]["data"] == [
        {"time": 1_700_000_060, "value": 2.0},
        {"time": 1_700_000_120, "value": 3.0},
    ]
    assert result.param_schema[0]["key"] == "1"
    assert module.run_calls[0][1][0]["time"] == 1_700_000_000_000
    assert module.run_calls[0][2] == {1: 2}


def test_pine_adapter_rejects_host_context_before_execution(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _FakePineModule(
        _analysis("indicator", "request.security", "plot"),
        _runtime_output(),
    )
    monkeypatch.setattr(pine_adapter, "_load_module", lambda: module)

    result = pine_adapter.execute_pine_script(
        script='indicator("Context")\nplot(request.security("AAPL", "D", close))',
        ohlcv=_bars(),
        executor_mode="inline",
    )

    assert result.ok is False
    assert result.code == "PINE_HOST_CAPABILITY_UNSUPPORTED"
    assert result.meta["blockedFeatures"] == ["request.security"]
    assert module.run_calls == []


def test_pine_adapter_rejects_unmapped_native_outputs(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _FakePineModule(
        _analysis("indicator", "plot"),
        _runtime_output(labels=[{"id": 1, "snapshots": []}]),
    )
    monkeypatch.setattr(pine_adapter, "_load_module", lambda: module)

    result = pine_adapter.execute_pine_script(
        script='indicator("Drawing")\nplot(close)',
        ohlcv=_bars(),
        executor_mode="inline",
    )

    assert result.ok is False
    assert result.code == "PINE_HOST_OUTPUT_UNSUPPORTED"
    assert result.meta["unsupportedOutputCollections"] == ["labels"]


def test_range_meta_keeps_pine_runtime_in_script_identity() -> None:
    meta = indicators_api._build_range_meta(indicators_api.IndicatorRangeRequest(
        clientId="pine-1",
        kind="script",
        runtime=PINE_COMPAT_RUNTIME_ID,
        symbol="BTCUSDT",
        interval="1m",
        script='indicator("Close")\nplot(close)',
        securityMode="unsafe",
        start=1,
        end=2,
    ))

    assert meta["runtime"] == PINE_COMPAT_RUNTIME_ID
    assert meta["indicatorId"].startswith("script:pine-compat:")
    assert meta["securityMode"] is None
    assert "scriptMode" not in meta


def test_custom_store_defaults_old_records_to_pyne_and_preserves_pine_updates(tmp_path) -> None:
    store = CustomIndicatorStore(tmp_path / "custom_indicators.json")
    legacy = store.upsert({"name": "Legacy", "script": "plot(close)"})
    pine = store.upsert({
        "name": "Pine",
        "runtime": PINE_COMPAT_RUNTIME_ID,
        "script": 'indicator("Close")\nplot(close)',
    })
    updated = store.upsert({"id": pine["id"], "description": "updated"})

    assert legacy["runtime"] == "pyne"
    assert updated["runtime"] == PINE_COMPAT_RUNTIME_ID
    assert updated["securityMode"] is None


@pytest.mark.anyio
async def test_compute_api_dispatches_explicit_pine_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _FakePineModule(_analysis("indicator", "plot"), _runtime_output())
    monkeypatch.setattr(pine_adapter, "_load_module", lambda: module)
    monkeypatch.setattr(indicators_api.config, "PINE_EXECUTOR_MODE", "inline")

    payload = await indicators_api.compute(indicators_api.ComputeRequest(
        mode="script",
        runtime=PINE_COMPAT_RUNTIME_ID,
        script='indicator("Close")\nplot(close)',
        ohlcv=_bars(),
    ))

    assert payload["ok"] is True
    assert payload["runtime"] == PINE_COMPAT_RUNTIME_ID
    assert payload["lines"][0]["id"] == "pine-plot-2"
    assert payload["meta"]["closedBarsOnly"] is True


@pytest.mark.anyio
async def test_pine_ws_subscription_is_closed_bar_only(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_snapshot(client_id: str, dm: Any, meta: dict[str, Any], bar_time: int = 0):
        del dm, bar_time
        return {
            "type": "indicator.snapshot",
            "clientId": client_id,
            "indicatorId": meta["indicatorId"],
            "runtime": PINE_COMPAT_RUNTIME_ID,
            "ok": True,
            "lines": [],
        }

    monkeypatch.setattr(stream_subscriptions, "_compute_pine_snapshot_message_async", fake_snapshot)

    class FakeDataManager:
        subscribe_kwargs: dict[str, Any] | None = None

        async def ensure_stream(self, *args: Any, **kwargs: Any) -> None:
            del args, kwargs

        def subscribe(self, **kwargs: Any) -> str:
            self.subscribe_kwargs = kwargs
            return "pine-handle"

    dm = FakeDataManager()
    sent: list[dict[str, Any]] = []

    async def send_json(payload: dict[str, Any]) -> bool:
        sent.append(payload)
        return True

    await stream_subscriptions.handle_pyne_indicator_subscribe(
        dm=dm,
        custom_handles={},
        custom_tasks={},
        queue=asyncio.Queue(),
        client_meta={},
        client_id="pine-ws",
        symbol="BTCUSDT",
        interval="1m",
        exchange="binance",
        market_type="spot",
        name="Pine Close",
        custom_id="",
        script='indicator("Close")\nplot(close)',
        params={},
        security_mode=None,
        runtime=PINE_COMPAT_RUNTIME_ID,
        history_limit=100,
        send_json=send_json,
        stream_consumer_id="pine-test",
        unsubscribe_client=lambda _client_id: asyncio.sleep(0),
        queue_message=lambda _queue, _message: None,
    )

    assert sent[0]["type"] == "indicator.subscribed"
    assert sent[0]["runtime"] == PINE_COMPAT_RUNTIME_ID
    assert sent[1]["type"] == "indicator.snapshot"
    assert dm.subscribe_kwargs is not None
    assert dm.subscribe_kwargs["event_types"] == {
        DataEventType.BAR_CLOSED,
        DataEventType.BAR_AMENDED,
        DataEventType.BACKFILL_COMPLETED,
    }


def test_pine_process_boundary_returns_structured_result() -> None:
    descriptor = pine_adapter.PineCompatRuntimeAdapter().descriptor()
    result = pine_adapter.execute_pine_script(
        script='//@version=6\nindicator("Close", overlay=true)\nplot(close)',
        ohlcv=_bars(),
        executor_mode="process",
        timeout_seconds=10,
    )

    if descriptor.available:
        assert result.ok is True
        assert result.lines[0]["data"][-1]["time"] == _bars()[-1]["time"]
    else:
        assert result.ok is False
        assert result.code == "PINE_RUNTIME_UNAVAILABLE"
