import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import BrandMark from "../brand/BrandMark.js";

export type AboutSettingsPanelProps = Record<string, never>;

export default function AboutSettingsPanel(props: AboutSettingsPanelProps) {
    void props;
    useLocale();
    const modifier = typeof navigator !== "undefined" && /Mac|iPhone|iPad|iPod/.test(navigator.platform) ? "⌘" : "Ctrl";
    return (
        <>
            <div className="st-group">
                <div className="st-about-header">
                    <div className="st-about-logo">
                        <BrandMark size={88} label="CandleScope" variant="full" />
                    </div>
                    <div className="st-about-name">
                        <span>Candle</span><span className="st-about-name-accent">Scope</span>
                    </div>
                    <div className="st-about-version">v0.2.0</div>
                    <div className="st-about-tagline">{t("settings.about.tagline")}</div>
                </div>
            </div>

            <div className="st-group">
                <div className="st-group-title">{t("settings.about.stack")}</div>
                <div className="st-about-stack">
                    <div className="st-stack-item">
                        <span className="st-stack-label">{t("settings.about.frontend")}</span>
                        <span className="st-stack-value">React + Lightweight Charts</span>
                    </div>
                    <div className="st-stack-item">
                        <span className="st-stack-label">{t("settings.about.backend")}</span>
                        <span className="st-stack-value">FastAPI + SQLite (WAL)</span>
                    </div>
                    <div className="st-stack-item">
                        <span className="st-stack-label">{t("settings.about.source")}</span>
                        <span className="st-stack-value">Binance REST + WebSocket</span>
                    </div>
                    <div className="st-stack-item">
                        <span className="st-stack-label">{t("settings.about.realtime")}</span>
                        <span className="st-stack-value">{t("settings.about.realtimeValue")}</span>
                    </div>
                </div>
            </div>

            <div className="st-group">
                <div className="st-group-title">{t("settings.about.shortcuts")}</div>
                <div className="st-about-stack">
                    {[
                        [`${modifier} + K`, t("settings.about.shortcutSearch")],
                        ["/", t("settings.about.shortcutSearchSlash")],
                        ["Esc", t("settings.about.shortcutSearchClose")],
                        [`${modifier} + Z`, t("settings.about.shortcutWorkspaceUndo")],
                        [`${modifier} + Shift + Z`, t("settings.about.shortcutWorkspaceRedo")],
                    ].map(([keys, description]) => (
                        <div className="st-stack-item st-shortcut-item" key={keys}>
                            <kbd className="st-stack-value">{keys}</kbd>
                            <span className="st-stack-label">{description}</span>
                        </div>
                    ))}
                </div>
            </div>
        </>
    );
}
