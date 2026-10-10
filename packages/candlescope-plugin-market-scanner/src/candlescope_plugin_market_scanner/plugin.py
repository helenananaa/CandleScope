"""Distribution-owned wrapper around the SDK Market Scanner reference kernel."""

from __future__ import annotations

from importlib.resources import files

from candlescope_plugin_sdk.platform_v2 import InvokeRequest, PluginManifest
from candlescope_plugin_sdk.platform_v2.errors import PlatformContractError
from candlescope_plugin_sdk.platform_v2.examples.market_scanner import (
    MarketScannerPlugin as ReferenceMarketScannerPlugin,
)
from candlescope_plugin_sdk.platform_v2.json_codec import loads_strict
from candlescope_plugin_sdk.platform_v2.server import serve_platform_plugin


def market_scanner_manifest() -> PluginManifest:
    resource = files(__package__).joinpath("manifest.json")
    return PluginManifest.from_wire(loads_strict(resource.read_bytes()))


_CONTRACT_LOCALIZATIONS = {
    "zh-CN": {
        "market scanner accepts only an empty scan command": "市场扫描器只接受空参数扫描命令",
        "market scanner completion token is stale": "市场扫描器完成令牌已失效",
        "Host returned invalid scanner settings": "宿主返回的扫描器设置无效",
        "Host returned an invalid symbol page": "宿主返回的标的页面无效",
        "market scanner phase is invalid": "市场扫描器阶段无效",
        "capabilityUnavailable": "{permission} 能力不可用",
    },
    "es": {
        "market scanner accepts only an empty scan command": "el escáner de mercado solo acepta un comando de escaneo vacío",
        "market scanner completion token is stale": "el token de finalización del escáner de mercado está caducado",
        "Host returned invalid scanner settings": "El host devolvió ajustes de escáner no válidos",
        "Host returned an invalid symbol page": "El host devolvió una página de símbolos no válida",
        "market scanner phase is invalid": "la fase del escáner de mercado no es válida",
        "capabilityUnavailable": "Capacidad no disponible: {permission}",
    },
    "fr": {
        "market scanner accepts only an empty scan command": (
            "Le scanner de marché n’accepte qu’une commande de scan sans paramètres"
        ),
        "market scanner completion token is stale": (
            "Le jeton d’achèvement du scanner de marché a expiré"
        ),
        "Host returned invalid scanner settings": (
            "L’hôte a renvoyé des paramètres de scanner invalides"
        ),
        "Host returned an invalid symbol page": (
            "L’hôte a renvoyé une page de symboles invalide"
        ),
        "market scanner phase is invalid": "La phase du scanner de marché est invalide",
        "capabilityUnavailable": "Capacité {permission} indisponible",
    },
    "ja": {
        "market scanner accepts only an empty scan command": "マーケットスキャナーは空のスキャンコマンドのみ受け付けます",
        "market scanner completion token is stale": "マーケットスキャナーの完了トークンは無効です",
        "Host returned invalid scanner settings": "ホストが返したスキャナー設定が不正です",
        "Host returned an invalid symbol page": "ホストが返した銘柄ページが不正です",
        "market scanner phase is invalid": "マーケットスキャナーの段階が不正です",
        "capabilityUnavailable": "{permission} 能力は利用できません",
    },
    "ko": {
        "market scanner accepts only an empty scan command": "시장 스캐너는 빈 인자 스캔 명령만 허용",
        "market scanner completion token is stale": "시장 스캐너 완료 토큰이 만료됨",
        "Host returned invalid scanner settings": "호스트가 반환한 스캐너 설정이 유효하지 않음",
        "Host returned an invalid symbol page": "호스트가 반환한 종목 페이지가 유효하지 않음",
        "market scanner phase is invalid": "시장 스캐너 단계가 유효하지 않음",
        "capabilityUnavailable": "{permission} 기능을 사용할 수 없음",
    },
    "pt-BR": {
        "market scanner accepts only an empty scan command": (
            "O scanner de mercado aceita apenas um comando de varredura sem parâmetros"
        ),
        "market scanner completion token is stale": (
            "O token de conclusão do scanner de mercado expirou"
        ),
        "Host returned invalid scanner settings": (
            "O Host devolveu configurações inválidas do scanner"
        ),
        "Host returned an invalid symbol page": ("O Host devolveu uma página de ativos inválida"),
        "market scanner phase is invalid": "A fase do scanner de mercado é inválida",
        "capabilityUnavailable": "A capacidade {permission} não está disponível",
    },
    "ru": {
        "market scanner accepts only an empty scan command": "Сканер рынка принимает только команду сканирования без параметров",
        "market scanner completion token is stale": "Токен завершения сканера рынка устарел",
        "Host returned invalid scanner settings": "Host вернул недопустимые настройки сканера",
        "Host returned an invalid symbol page": "Host вернул недопустимую страницу инструментов",
        "market scanner phase is invalid": "Недопустимая фаза сканера рынка",
        "capabilityUnavailable": "Возможность {permission} недоступна",
    },
    "zh-TW": {
        "market scanner accepts only an empty scan command": "市場掃描器只接受空參數掃描命令",
        "market scanner completion token is stale": "市場掃描器完成令牌已失效",
        "Host returned invalid scanner settings": "宿主傳回的掃描器設定無效",
        "Host returned an invalid symbol page": "宿主傳回的標的頁面無效",
        "market scanner phase is invalid": "市場掃描器階段無效",
        "capabilityUnavailable": "{permission} 能力不可用",
    },
    "de": {
        "market scanner accepts only an empty scan command": (
            "Der Markt-Scanner akzeptiert nur einen Scan-Befehl ohne Parameter"
        ),
        "market scanner completion token is stale": (
            "Das Abschluss-Token des Markt-Scanners ist abgelaufen"
        ),
        "Host returned invalid scanner settings": (
            "Der Host hat ungültige Scanner-Einstellungen zurückgegeben"
        ),
        "Host returned an invalid symbol page": (
            "Der Host hat eine ungültige Symbolseite zurückgegeben"
        ),
        "market scanner phase is invalid": "Die Phase des Markt-Scanners ist ungültig",
        "capabilityUnavailable": "Fähigkeit {permission} nicht verfügbar",
    },
    "it": {
        "market scanner accepts only an empty scan command": (
            "Lo scanner di mercato accetta solo un comando di scansione senza parametri"
        ),
        "market scanner completion token is stale": (
            "Il token di completamento dello scanner di mercato è scaduto"
        ),
        "Host returned invalid scanner settings": (
            "L'Host ha restituito impostazioni dello scanner non valide"
        ),
        "Host returned an invalid symbol page": (
            "L'Host ha restituito una pagina di simboli non valida"
        ),
        "market scanner phase is invalid": "La fase dello scanner di mercato non è valida",
        "capabilityUnavailable": "Capacità {permission} non disponibile",
    },
    "id": {
        "market scanner accepts only an empty scan command": (
            "Pemindai pasar hanya menerima perintah pindai tanpa parameter"
        ),
        "market scanner completion token is stale": (
            "Token penyelesaian pemindai pasar sudah kedaluwarsa"
        ),
        "Host returned invalid scanner settings": (
            "Host mengembalikan pengaturan pemindai yang tidak valid"
        ),
        "Host returned an invalid symbol page": (
            "Host mengembalikan halaman simbol yang tidak valid"
        ),
        "market scanner phase is invalid": "Fase pemindai pasar tidak valid",
        "capabilityUnavailable": "Kemampuan {permission} tidak tersedia",
    },
    "tr": {
        "market scanner accepts only an empty scan command": (
            "Piyasa tarayıcısı yalnızca parametresiz bir tarama komutunu kabul eder"
        ),
        "market scanner completion token is stale": (
            "Piyasa tarayıcısının tamamlanma jetonunun süresi doldu"
        ),
        "Host returned invalid scanner settings": "Host geçersiz tarayıcı ayarları döndürdü",
        "Host returned an invalid symbol page": "Host geçersiz bir sembol sayfası döndürdü",
        "market scanner phase is invalid": "Piyasa tarayıcısının aşaması geçersiz",
        "capabilityUnavailable": "{permission} yeteneği kullanılamıyor",
    },
    "vi": {
        "market scanner accepts only an empty scan command": (
            "Bộ quét thị trường chỉ chấp nhận lệnh quét không có tham số"
        ),
        "market scanner completion token is stale": (
            "Token hoàn tất của bộ quét thị trường đã hết hạn"
        ),
        "Host returned invalid scanner settings": "Host trả về cài đặt bộ quét không hợp lệ",
        "Host returned an invalid symbol page": "Host trả về trang mã không hợp lệ",
        "market scanner phase is invalid": "Giai đoạn của bộ quét thị trường không hợp lệ",
        "capabilityUnavailable": "Năng lực {permission} không khả dụng",
    },
    "pl": {
        "market scanner accepts only an empty scan command": (
            "Skaner rynku akceptuje tylko polecenie skanowania bez parametrów"
        ),
        "market scanner completion token is stale": "Token zakończenia skanera rynku wygasł",
        "Host returned invalid scanner settings": (
            "Host zwrócił nieprawidłowe ustawienia skanera"
        ),
        "Host returned an invalid symbol page": (
            "Host zwrócił nieprawidłową stronę symboli"
        ),
        "market scanner phase is invalid": "Faza skanera rynku jest nieprawidłowa",
        "capabilityUnavailable": "Zdolność {permission} jest niedostępna",
    },
}


def _localized_contract_error(
    error: PlatformContractError, locale: str | None
) -> PlatformContractError:
    candidate = (locale or "").strip().lower()
    messages = None
    while candidate:
        messages = next(
            (value for key, value in _CONTRACT_LOCALIZATIONS.items() if key.lower() == candidate),
            None,
        )
        if messages is not None:
            break
        candidate = candidate.rpartition("-")[0]
    if messages is None:
        return error
    message = messages.get(error.message)
    if message is None and error.message.endswith(" capability is unavailable"):
        permission = error.message.removesuffix(" capability is unavailable")
        template = messages.get("capabilityUnavailable")
        if template is not None:
            message = template.replace("{permission}", permission)
    if message is None:
        return error
    return PlatformContractError(error.code, message, error.path)


class MarketScannerPlugin(ReferenceMarketScannerPlugin):
    """The packaged scanner owns its manifest and locale-aware validation errors."""

    def __init__(self) -> None:
        super().__init__()
        self._manifest = market_scanner_manifest()

    def invoke(self, request: InvokeRequest):  # type: ignore[no-untyped-def]
        try:
            return super().invoke(request)
        except PlatformContractError as error:
            raise _localized_contract_error(error, request.request_context.locale) from error

    def complete_host_call(self, token, response):  # type: ignore[no-untyped-def]
        state = self._pending.get(token)
        locale = state.context.locale if state is not None else None
        try:
            return super().complete_host_call(token, response)
        except PlatformContractError as error:
            raise _localized_contract_error(error, locale) from error


def main() -> int:
    return serve_platform_plugin(MarketScannerPlugin())


if __name__ == "__main__":
    raise SystemExit(main())
