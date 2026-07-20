from __future__ import annotations

from types import SimpleNamespace

from scripts import ensure_pine_runtime
from scripts import managed_plugin_installer as installer
from scripts.managed_plugin_probes import run_probe


def test_real_registry_migrates_pine_to_managed_plugin_contract() -> None:
    plugins = installer.load_plugin_registry()
    pine = next(item for item in plugins if item.lock.plugin_id == "pine-compat")

    assert pine.auto_install is True
    assert pine.lock.installer_kind == "python-wheel"
    assert pine.lock.probe_kind == "pine-runtime-v1"
    assert pine.lock.legacy_stamp_files == ("pine-runtime-install.json",)


def test_pine_probe_remains_host_specific() -> None:
    module = SimpleNamespace(
        analyze_script=lambda source: {"schemaVersion": 3},
        run_script=lambda source, bars: {
            "schemaVersion": 7,
            "plots": [{"id": "sma"}],
        },
    )

    result = run_probe(
        "pine-runtime-v1",
        module,
        {
            "probe": "pine-runtime-v1",
            "analysisSchemaVersion": 3,
            "runtimeSchemaVersion": 7,
        },
    )

    assert result == {"analysisSchemaVersion": 3, "runtimeSchemaVersion": 7}


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
