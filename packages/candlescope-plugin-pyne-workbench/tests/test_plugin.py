from __future__ import annotations

from importlib.resources import files

import jsonschema
import pytest

from candlescope_plugin_sdk.platform_v2 import (
    ActivationRequest,
    CapabilityGrant,
    HostCallInvocation,
    InvokeRequest,
    RequestContext,
    RpcSuccess,
    manifest_schema,
)
from candlescope_plugin_sdk.platform_v2.errors import PlatformContractError
from candlescope_plugin_pyne_workbench import PyneWorkbenchPlugin, pyne_workbench_manifest
from candlescope_plugin_pyne_workbench.plugin import (
    _CONTRACT_LOCALIZATIONS,
    _localized_contract_error,
)


CHART = {
    "schemaVersion": "candlescope.chart-context/1",
    "chartId": "main-chart",
    "revision": 7,
    "active": True,
    "context": {"mode": "live", "exchange": "binance", "marketType": "spot"},
    "series": {"symbol": "BTCUSDT", "interval": "1m"},
    "updatedAtMs": 300_000,
}
BARS = {
    "data": [
        {"time": 60, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 1, "is_closed": True},
        {
            "time": 120,
            "open": 10,
            "high": 12,
            "low": 9,
            "close": 11,
            "volume": 2,
            "is_closed": True,
        },
        {
            "time": 180,
            "open": 11,
            "high": 13,
            "low": 10,
            "close": 12,
            "volume": 3,
            "is_closed": True,
        },
    ],
    "coverage": {"allRowsFinal": True},
}


def _plugin() -> PyneWorkbenchPlugin:
    plugin = PyneWorkbenchPlugin()
    manifest = pyne_workbench_manifest()
    plugin.activate(
        ActivationRequest(
            "workbench-test",
            1,
            tuple(
                CapabilityGrant(f"cap-{item.id}", item.id, item.scope)
                for item in manifest.permissions.required
            ),
        )
    )
    return plugin


def _invoke(plugin: PyneWorkbenchPlugin, contribution: str, input_value: dict):
    return plugin.invoke(
        InvokeRequest(
            contribution,
            input_value,
            RequestContext(contribution, True, 1, f"trace-{contribution}"),
        )
    )


def _complete(plugin: PyneWorkbenchPlugin, call: HostCallInvocation, result: dict):
    return plugin.complete_host_call(call.token, RpcSuccess("host", result, 1))


def test_manifest_is_independent_v2_plugin_with_bounded_capabilities() -> None:
    manifest = pyne_workbench_manifest()
    jsonschema.validate(manifest.to_wire(), manifest_schema())
    assert manifest.plugin.id == "candlescope.pyne-workbench"
    assert {item.kind for item in manifest.contributions} >= {
        "command/1",
        "view/1",
        "chart-layer/2",
        "strategy-provider/1",
    }
    assert "pyne-workbench" in {item.id for item in manifest.backend_entrypoints}
    run = next(item for item in manifest.contributions if item.id == "run")
    assert run.localizations["pt-BR"]["title"] == "Executar Pyne no gráfico atual"
    assert run.localizations["pt-BR"]["schema"]["properties"]["source"]["title"] == (
        "Código-fonte Pyne"
    )
    assert [item.id for item in manifest.permissions.required] == [
        "chart.context.read",
        "market.bars.read",
        "chart.layer.publish",
    ]


def test_sandbox_ui_owns_zh_cn_english_and_japanese_copy() -> None:
    web = files("candlescope_plugin_pyne_workbench").joinpath("web")
    html = web.joinpath("index.html").read_text(encoding="utf-8")
    javascript = web.joinpath("app.js").read_text(encoding="utf-8")

    assert 'data-i18n="statusWaiting"' in html
    assert '"zh-CN": {' in javascript
    assert '"zh-TW": {' in javascript
    assert "en: {" in javascript
    assert "es: {" in javascript
    assert "Banco de trabajo Pyne" in javascript
    assert "Esperando a CandleScope" in javascript
    assert "fr: {" in javascript
    assert "Atelier Pyne" in javascript
    assert "ja: {" in javascript
    assert "Pyne ワークベンチ" in javascript
    assert "ko: {" in javascript
    assert "Pyne 작업대" in javascript
    assert '"pt-BR": {' in javascript
    assert "Aguardando conexão do CandleScope" in javascript
    assert "Executar Pyne no gráfico atual" in javascript
    assert "ru: {" in javascript
    assert "Верстак Pyne" in javascript
    assert "de: {" in javascript
    assert "Pyne-Werkbank" in javascript
    assert "it: {" in javascript
    assert "Banco di lavoro Pyne" in javascript
    assert "id: {" in javascript
    assert "Meja kerja Pyne" in javascript
    assert "tr: {" in javascript
    assert "Pyne çalışma tezgâhı" in javascript
    assert "vi: {" in javascript
    assert "Bàn làm việc Pyne" in javascript
    assert "pl: {" in javascript
    assert "Warsztat Pyne" in javascript
    assert "等待 CandleScope 連線" in javascript
    assert "applyLocale(payload.locale)" in javascript
    assert 'setStatus("statusRejected")' in javascript
    assert "ecrã" not in javascript
    assert "ficheiro" not in javascript
    assert "utilizador" not in javascript
    assert "percentagem" not in javascript


def test_packaged_manifest_owns_spanish_localizations() -> None:
    manifest = pyne_workbench_manifest()
    by_id = {item.id: item for item in manifest.contributions}
    assert by_id["run"].localizations["es"]["title"] == "Ejecutar Pyne en el gráfico actual"
    run_schema = by_id["run"].localizations["es"]["schema"]["properties"]
    assert run_schema["source"]["title"] == "Código fuente Pyne"
    assert run_schema["lookbackBars"]["title"] == "Barras de retrospectiva"
    assert (
        by_id["start-session"].localizations["es"]["title"] == "Iniciar sesión incremental de Pyne"
    )
    push_schema = by_id["push-bar"].localizations["es"]["schema"]["properties"]
    assert push_schema["open"]["title"] == "Apertura"
    assert push_schema["close"]["title"] == "Cierre"
    assert (
        by_id["snapshot-session"].localizations["es"]["title"]
        == "Crear instantánea de la sesión Pyne"
    )
    assert by_id["close-session"].localizations["es"]["title"] == "Cerrar sesión Pyne"
    assert (
        by_id["pyne-strategy"].localizations["es"]["title"]
        == "Proveedor de estrategia de prueba retrospectiva Pyne"
    )
    assert by_id["workbench-view"].localizations["es"]["title"] == "Banco de trabajo Pyne"
    assert by_id["pyne-output"].localizations["es"]["title"] == "Salida Pyne"


def test_manifest_owns_french_contribution_copy() -> None:
    manifest = pyne_workbench_manifest()
    titles = {
        item.id: item.localizations["fr"]["title"]
        for item in manifest.contributions
        if "fr" in item.localizations
    }
    assert titles["run"] == "Exécuter Pyne sur le graphique actuel"
    assert titles["workbench-view"] == "Atelier Pyne"
    assert titles["pyne-strategy"] == "Fournisseur de stratégie backtest Pyne"
    run = next(item for item in manifest.contributions if item.id == "run")
    assert run.localizations["fr"]["schema"]["properties"]["lookbackBars"]["title"] == (
        "Barres de rétrospection"
    )


def test_workbench_errors_follow_french_regional_locale() -> None:
    error = PlatformContractError("INVALID_CONTRACT", "Pyne session is not active")
    translated = _localized_contract_error(error, "fr-CA")
    assert translated.message == "La session Pyne n’est pas active"
    capability = PlatformContractError(
        "INVALID_CONTRACT", "chart.layer.publish capability is unavailable"
    )
    assert _localized_contract_error(capability, "fr").message == (
        "Capacité chart.layer.publish indisponible"
    )
    plugin = _plugin()
    with pytest.raises(PlatformContractError, match="n’est pas invocable"):
        plugin.invoke(
            InvokeRequest(
                "not-a-contribution",
                {},
                RequestContext("not-a-contribution", True, 1, "trace-fr", locale="fr-CA"),
            )
        )


def test_runtime_contract_errors_cover_every_manifest_locale() -> None:
    manifest = pyne_workbench_manifest()
    declared = {
        locale
        for contribution in manifest.contributions
        for locale in contribution.localizations
    }
    assert declared == set(_CONTRACT_LOCALIZATIONS)

    error = PlatformContractError("INVALID_CONTRACT", "Pyne session is not active")
    expected = {
        "zh-CN": "Pyne 会话未激活",
        "es": "La sesión de Pyne no está activa",
        "fr": "La session Pyne n’est pas active",
        "ja": "Pyne セッションは有効ではありません",
        "ko": "Pyne 세션이 활성 상태가 아님",
        "pt-BR": "A sessão Pyne não está ativa",
        "ru": "Сессия Pyne не активна",
        "zh-TW": "Pyne 工作階段尚未啟用",
        "de": "Die Pyne-Sitzung ist nicht aktiv",
        "it": "La sessione Pyne non è attiva",
        "id": "Sesi Pyne tidak aktif",
        "tr": "Pyne oturumu etkin değil",
        "vi": "Phiên Pyne không hoạt động",
        "pl": "Sesja Pyne nie jest aktywna",
    }
    for locale, message in expected.items():
        translated = _localized_contract_error(error, locale)
        assert translated.message == message
        assert translated is not error

    assert _localized_contract_error(error, "es-MX").message == expected["es"]
    assert _localized_contract_error(error, "pt-br").message == expected["pt-BR"]
    assert _localized_contract_error(error, "ru-RU").message == expected["ru"]
    assert _localized_contract_error(error, "zh-tw").message == expected["zh-TW"]
    assert _localized_contract_error(error, "de-DE").message == expected["de"]
    assert _localized_contract_error(error, "it-IT").message == expected["it"]
    assert _localized_contract_error(error, "id-ID").message == expected["id"]
    assert _localized_contract_error(error, "tr-TR").message == expected["tr"]
    assert _localized_contract_error(error, "vi-VN").message == expected["vi"]
    assert _localized_contract_error(error, "pl-PL").message == expected["pl"]


def test_manifest_owns_japanese_command_and_schema_copy() -> None:
    manifest = pyne_workbench_manifest()
    run = next(item for item in manifest.contributions if item.id == "run")
    assert run.localizations["ja"]["title"] == "現在のチャートで Pyne を実行"
    assert run.localizations["ja"]["schema"]["properties"]["lookbackBars"]["title"] == "遡及本数"
    view = next(item for item in manifest.contributions if item.id == "workbench-view")
    assert view.localizations["ja"]["title"] == "Pyne ワークベンチ"


def test_plugin_owned_errors_follow_japanese_locale() -> None:
    error = PlatformContractError(
        "INVALID_CONTRACT",
        "Pyne workbench contribution is not invokable",
        "invoke.unknown",
    )
    translated = _localized_contract_error(error, "ja-JP")
    assert translated.message == "Pyne ワークベンチのコントリビューションは実行できません"
    plugin = _plugin()
    with pytest.raises(PlatformContractError, match="実行できません"):
        plugin.invoke(
            InvokeRequest(
                "unknown",
                {},
                RequestContext("unknown", True, 1, "trace-ja", "ja"),
            )
        )
def test_plugin_owned_korean_errors_follow_ko_and_ko_kr() -> None:
    plugin = _plugin()
    with pytest.raises(PlatformContractError, match="호출할 수 없음"):
        plugin.invoke(
            InvokeRequest(
                "not-a-command",
                {},
                RequestContext("not-a-command", True, 1, "trace-ko", locale="ko-KR"),
            )
        )
    error = PlatformContractError("INVALID_CONTRACT", "workbench phase is invalid")
    assert _localized_contract_error(error, "ko").message == "작업대 단계가 유효하지 않음"
    assert _localized_contract_error(error, "ko-KR").message == "작업대 단계가 유효하지 않음"
    english = PlatformContractError("INVALID_CONTRACT", "workbench phase is invalid")
    assert _localized_contract_error(english, "en") is english


def test_manifest_owns_korean_contribution_copy() -> None:
    manifest = pyne_workbench_manifest()
    localized = [item for item in manifest.contributions if item.localizations]
    assert localized
    for item in localized:
        assert "ko" in item.localizations, item.id
        korean = item.localizations["ko"]
        assert korean["title"]
        chinese = item.localizations["zh-CN"]
        if "schema" in chinese:
            assert set(korean["schema"]["properties"]) == set(chinese["schema"]["properties"])


def test_manifest_owns_zh_tw_contribution_copy() -> None:
    manifest = pyne_workbench_manifest()
    run = next(item for item in manifest.contributions if item.id == "run")
    assert run.localizations["zh-TW"]["title"] == "在當前圖表執行 Pyne"
    view = next(item for item in manifest.contributions if item.id == "workbench-view")
    assert view.localizations["zh-TW"]["title"] == "Pyne 工作台"


def test_batch_command_reads_chart_bars_and_publishes_render_v2() -> None:
    plugin = _plugin()
    first = _invoke(
        plugin,
        "run",
        {"source": 'indicator("Test")\nplot(close, "Close")', "lookbackBars": 3},
    )
    assert isinstance(first, HostCallInvocation) and first.call.method == "chart.context.read"
    second = _complete(plugin, first, CHART)
    assert isinstance(second, HostCallInvocation) and second.call.method == "market.bars.read"
    third = _complete(plugin, second, BARS)
    assert isinstance(third, HostCallInvocation) and third.call.method == "chart.layer.publish"
    assert third.call.params["render"]["schemaVersion"] == "candlescope.render/2"
    assert third.call.params["render"]["items"][0]["type"] == "polyline"
    done = _complete(plugin, third, {"published": True, "revision": 1})
    assert done["completed"] is True
    assert done["layerPublished"] is True
    assert done["pyneOutputSchema"] == 2


def test_batch_command_brokers_exact_request_data_before_publish() -> None:
    plugin = _plugin()
    first = _invoke(
        plugin,
        "run",
        {
            "source": (
                'requested = request.security("BTCUSDT", "5m", close)\nplot(requested, "Requested")'
            ),
            "lookbackBars": 3,
        },
    )
    second = _complete(plugin, first, CHART)
    broker = _complete(plugin, second, BARS)
    assert isinstance(broker, HostCallInvocation)
    assert broker.call.method == "market.bars.read"
    assert broker.call.params["series"] == {"symbol": "BTCUSDT", "interval": "5m"}
    publish = _complete(plugin, broker, BARS)
    assert isinstance(publish, HostCallInvocation)
    assert publish.call.method == "chart.layer.publish"
    done = _complete(plugin, publish, {"published": True, "revision": 2})
    assert done["completed"] is True


INCREMENTAL_SOURCE = """
indicator("Session", mode="incremental", overlay=True)
def on_bar(ctx, bar):
    ctx.plot("Close", bar.close)
"""


def test_incremental_session_start_push_snapshot_and_close() -> None:
    plugin = _plugin()
    first = _invoke(
        plugin,
        "start-session",
        {
            "sessionId": "dev-one",
            "source": INCREMENTAL_SOURCE,
            "lookbackBars": 3,
            "retentionBars": 10,
        },
    )
    second = _complete(plugin, first, CHART)
    publish = _complete(plugin, second, BARS)
    assert isinstance(publish, HostCallInvocation)
    started = _complete(plugin, publish, {"published": True, "revision": 3})
    assert started["completed"] is True
    assert started["sessionId"] == "dev-one"

    pushed = _invoke(
        plugin,
        "push-bar",
        {
            "sessionId": "dev-one",
            "time": 240,
            "open": 12,
            "high": 14,
            "low": 11,
            "close": 13,
            "volume": 4,
            "preview": False,
        },
    )
    assert isinstance(pushed, HostCallInvocation)
    pushed_done = _complete(plugin, pushed, {"published": True, "revision": 4})
    assert pushed_done["operation"] == "push-bar"

    snapshot = _invoke(plugin, "snapshot-session", {"sessionId": "dev-one"})
    assert isinstance(snapshot, HostCallInvocation)
    snapshot_done = _complete(plugin, snapshot, {"published": True, "revision": 5})
    assert snapshot_done["operation"] == "snapshot-session"

    closed = _invoke(plugin, "close-session", {"sessionId": "dev-one"})
    assert closed["closed"] is True


NEW_HOST_LOCALES = ("de", "it", "id", "tr", "vi", "pl")

NEW_HOST_REGIONAL = {
    "de": "de-DE",
    "it": "it-IT",
    "id": "id-ID",
    "tr": "tr-TR",
    "vi": "vi-VN",
    "pl": "pl-PL",
}

WORKBENCH_RUN_TITLES = {
    "de": "Pyne auf dem aktuellen Chart ausführen",
    "it": "Esegui Pyne sul grafico attuale",
    "id": "Jalankan Pyne pada grafik saat ini",
    "tr": "Geçerli grafikte Pyne çalıştır",
    "vi": "Chạy Pyne trên biểu đồ hiện tại",
    "pl": "Uruchom Pyne na bieżącym wykresie",
}

WORKBENCH_VIEW_TITLES = {
    "de": "Pyne-Werkbank",
    "it": "Banco di lavoro Pyne",
    "id": "Meja kerja Pyne",
    "tr": "Pyne çalışma tezgâhı",
    "vi": "Bàn làm việc Pyne",
    "pl": "Warsztat Pyne",
}

WORKBENCH_NOT_INVOKABLE = {
    "de": "Der Beitrag der Pyne-Werkbank kann nicht aufgerufen werden",
    "it": "Il contributo del banco di lavoro Pyne non è invocabile",
    "id": "Kontribusi meja kerja Pyne tidak dapat dipanggil",
    "tr": "Pyne çalışma tezgâhı katkısı çağrılamaz",
    "vi": "Đóng góp bàn làm việc Pyne không thể gọi",
    "pl": "Wkład warsztatu Pyne nie może zostać wywołany",
}

WORKBENCH_BOUNDED_STRING = {
    "de": "source muss eine längenbeschränkte Zeichenkette sein",
    "it": "source deve essere una stringa di lunghezza limitata",
    "id": "source harus berupa string dengan panjang terbatas",
    "tr": "source uzunluğu sınırlı bir dize olmalıdır",
    "vi": "source phải là chuỗi có độ dài giới hạn",
    "pl": "source musi być łańcuchem o ograniczonej długości",
}

WORKBENCH_SANDBOX_MARKERS = {
    "de": "Pyne-Werkbank",
    "it": "Banco di lavoro Pyne",
    "id": "Meja kerja Pyne",
    "tr": "Pyne çalışma tezgâhı",
    "vi": "Bàn làm việc Pyne",
    "pl": "Warsztat Pyne",
}


@pytest.mark.parametrize("locale", NEW_HOST_LOCALES)
def test_new_host_locales_own_contribution_copy_and_plugin_errors(locale: str) -> None:
    manifest = pyne_workbench_manifest()
    localized = [item for item in manifest.contributions if item.localizations]
    assert localized
    for item in localized:
        assert locale in item.localizations, item.id
        copy = item.localizations[locale]
        assert copy["title"]
        chinese = item.localizations["zh-CN"]
        if "schema" in chinese:
            assert set(copy["schema"]["properties"]) == set(chinese["schema"]["properties"])
            for key, value in chinese["schema"]["properties"].items():
                assert copy["schema"]["properties"][key]["title"]
                if "title" in value:
                    assert copy["schema"]["properties"][key]["title"] != value["title"]
    run = next(item for item in manifest.contributions if item.id == "run")
    assert run.localizations[locale]["title"] == WORKBENCH_RUN_TITLES[locale]
    view = next(item for item in manifest.contributions if item.id == "workbench-view")
    assert view.localizations[locale]["title"] == WORKBENCH_VIEW_TITLES[locale]

    error = PlatformContractError(
        "INVALID_CONTRACT",
        "Pyne workbench contribution is not invokable",
        "invoke.unknown",
    )
    translated = _localized_contract_error(error, locale)
    assert translated.message == WORKBENCH_NOT_INVOKABLE[locale]
    regional = _localized_contract_error(error, NEW_HOST_REGIONAL[locale])
    assert regional.message == WORKBENCH_NOT_INVOKABLE[locale]
    assert (regional.code, regional.path) == (error.code, error.path)
    bounded = PlatformContractError("INVALID_CONTRACT", "source must be a bounded string")
    assert _localized_contract_error(bounded, locale).message == WORKBENCH_BOUNDED_STRING[locale]
    capability = PlatformContractError(
        "INVALID_CONTRACT", "chart.layer.publish capability is unavailable"
    )
    localized_capability = _localized_contract_error(capability, NEW_HOST_REGIONAL[locale])
    assert "chart.layer.publish" in localized_capability.message
    assert localized_capability.message != capability.message

    plugin = _plugin()
    with pytest.raises(PlatformContractError, match=WORKBENCH_NOT_INVOKABLE[locale]):
        plugin.invoke(
            InvokeRequest(
                "not-a-contribution",
                {},
                RequestContext(
                    "not-a-contribution",
                    True,
                    1,
                    f"trace-{locale}",
                    locale=NEW_HOST_REGIONAL[locale],
                ),
            )
        )


@pytest.mark.parametrize("locale", NEW_HOST_LOCALES)
def test_sandbox_ui_owns_new_host_locale_catalogs(locale: str) -> None:
    javascript = (
        files("candlescope_plugin_pyne_workbench")
        .joinpath("web")
        .joinpath("app.js")
        .read_text(encoding="utf-8")
    )
    assert f"{locale}: {{" in javascript or f'"{locale}": {{' in javascript
    assert WORKBENCH_SANDBOX_MARKERS[locale] in javascript
    assert "Render IR v2" in javascript
    assert "candle" in javascript
    assert "table" in javascript
    assert "linefill" in javascript
