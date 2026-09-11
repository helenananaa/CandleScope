from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "candlescope_plugin_pyne_workbench"


def test_manifest_and_sandbox_ship_zh_tw_copy() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    titles = {
        item["id"]: item["configuration"]["localizations"]["zh-TW"]["title"]
        for item in manifest["contributions"]
    }
    assert titles["run"] == "在當前圖表執行 Pyne"
    assert titles["workbench-view"] == "Pyne 工作台"
    assert titles["pyne-output"] == "Pyne 輸出"
    javascript = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert '"zh-TW": {' in javascript
    assert "等待 CandleScope 連線" in javascript
    assert "已連線 · 命令從外掛面板執行" in javascript
    assert titles["run"]
    th_titles = {
        item["id"]: item["configuration"]["localizations"]["th"]["title"]
        for item in manifest["contributions"]
    }
    nl_titles = {
        item["id"]: item["configuration"]["localizations"]["nl"]["title"]
        for item in manifest["contributions"]
    }
    assert th_titles["run"] == "รัน Pyne บนชาร์ตปัจจุบัน"
    assert th_titles["workbench-view"] == "โต๊ะงาน Pyne"
    assert nl_titles["run"] == "Pyne uitvoeren op de huidige grafiek"
    assert nl_titles["workbench-view"] == "Pyne-werkbank"
    assert "th: {" in javascript
    assert "โต๊ะงาน Pyne" in javascript
    assert "nl: {" in javascript
    assert "Pyne-werkbank" in javascript
    for item in manifest["contributions"]:
        locales = item["configuration"]["localizations"]
        assert "uk" not in locales
        assert len(locales) <= 16
