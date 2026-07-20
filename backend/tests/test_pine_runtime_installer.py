from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from scripts import ensure_pine_runtime
from scripts import managed_plugin_installer as installer
from scripts.managed_plugin_probes import ProbeError, run_probe


def test_real_registry_migrates_pine_to_managed_plugin_contract() -> None:
    plugins = installer.load_plugin_registry()
    pine = next(item for item in plugins if item.lock.plugin_id == "pine-compat")

    assert pine.auto_install is True
    assert pine.lock.installer_kind == "python-wheel"
    assert pine.lock.probe_kind == "pine-runtime-v1"
    assert pine.lock.legacy_stamp_files == ("pine-runtime-install.json",)


def test_pine_probe_remains_host_specific() -> None:
    module = SimpleNamespace(
        analyze_script=lambda source: {"schemaVersion": 5},
        run_script=lambda source, bars: {
            "schemaVersion": 8,
            "renderMetadataVersion": 1,
            "plots": [{"id": "sma"}],
        },
    )

    result = run_probe(
        "pine-runtime-v1",
        module,
        {
            "probe": "pine-runtime-v1",
            "analysisSchemaVersion": 5,
            "runtimeSchemaVersion": 8,
        },
    )

    assert result == {"analysisSchemaVersion": 5, "runtimeSchemaVersion": 8}


class _RealtimeProbeSession:
    schema_version = 1

    def __init__(self) -> None:
        self.confirmed_bars = 0
        self.last_confirmed_time = None
        self.forming_time = None
        self._intrabar = 1.0

    @staticmethod
    def _result(regular: float, intrabar: float) -> dict[str, object]:
        return {
            "plots": [
                {"values": [1.0, regular]},
                {"values": [1.0, intrabar]},
            ]
        }

    def seed(self, bars: list[dict[str, object]]) -> dict[str, object]:
        self.confirmed_bars = len(bars)
        self.last_confirmed_time = bars[-1]["time"]
        return self._result(1.0, 1.0)

    def update_forming(self, bar: dict[str, object]) -> dict[str, object]:
        self.forming_time = bar["time"]
        self._intrabar += 1.0
        return self._result(2.0, self._intrabar)

    def update_confirmed(self, bar: dict[str, object]) -> dict[str, object]:
        self.confirmed_bars += 1
        self.last_confirmed_time = bar["time"]
        self.forming_time = None
        self._intrabar += 1.0
        return self._result(2.0, self._intrabar)


def _pine_v2_probe_module() -> SimpleNamespace:
    return SimpleNamespace(
        RENDER_METADATA_VERSION=1,
        REALTIME_SESSION_SCHEMA_VERSION=1,
        analyze_script=lambda source: {"schemaVersion": 5},
        run_script=lambda source, bars: {
            "schemaVersion": 8,
            "renderMetadataVersion": 1,
            "plots": [{"id": "sma"}],
        },
        create_realtime_session=lambda source: _RealtimeProbeSession(),
    )


def test_pine_v2_probe_requires_and_executes_realtime_session_abi() -> None:
    result = run_probe(
        "pine-runtime-v2",
        _pine_v2_probe_module(),
        {
            "probe": "pine-runtime-v2",
            "analysisSchemaVersion": 5,
            "runtimeSchemaVersion": 8,
            "renderMetadataVersion": 1,
            "realtimeSessionSchemaVersion": 1,
        },
    )

    assert result == {
        "analysisSchemaVersion": 5,
        "runtimeSchemaVersion": 8,
        "renderMetadataVersion": 1,
        "realtimeSessionSchemaVersion": 1,
    }


def test_pine_v2_probe_rejects_runtime_without_realtime_abi() -> None:
    module = _pine_v2_probe_module()
    del module.REALTIME_SESSION_SCHEMA_VERSION

    with pytest.raises(ProbeError, match="realtime session schema mismatch"):
        run_probe(
            "pine-runtime-v2",
            module,
            {
                "probe": "pine-runtime-v2",
                "analysisSchemaVersion": 5,
                "runtimeSchemaVersion": 8,
                "renderMetadataVersion": 1,
                "realtimeSessionSchemaVersion": 1,
            },
        )


def test_legacy_pine_lock_opt_in_upgrades_to_v2_probe(tmp_path) -> None:
    value = json.loads(
        ensure_pine_runtime._default_lock_path().read_text(encoding="utf-8")
    )
    value["renderMetadataVersion"] = 1
    value["realtimeSessionSchemaVersion"] = 1
    lock_path = tmp_path / "CANDLESCOPE_RUNTIME.json"
    lock_path.write_text(json.dumps(value), encoding="utf-8")

    lock = installer.load_plugin_lock(lock_path)

    assert lock.probe_kind == "pine-runtime-v2"
    assert lock.probe_config["renderMetadataVersion"] == 1
    assert lock.probe_config["realtimeSessionSchemaVersion"] == 1


def test_legacy_pine_entrypoint_delegates_to_generic_installer(monkeypatch) -> None:
    lock = SimpleNamespace(plugin_id="pine-compat")
    captured: dict[str, object] = {}
    monkeypatch.setattr(ensure_pine_runtime, "load_plugin_lock", lambda path: lock)
    monkeypatch.setattr(
        ensure_pine_runtime,
        "default_cache_dir",
        lambda: ensure_pine_runtime._default_lock_path().parent,
    )

    def fake_ensure(value, **kwargs):
        captured["lock"] = value
        captured.update(kwargs)
        return False

    monkeypatch.setattr(ensure_pine_runtime, "ensure_managed_plugin", fake_ensure)

    assert ensure_pine_runtime.main(["--check"]) == 1
    assert captured["lock"] is lock
    assert captured["check"] is True
