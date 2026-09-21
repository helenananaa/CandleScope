import { useEffect, useState } from "react";
import { shortcutModifier } from "../../shared/shortcutModifier.js";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import BrandMark from "../brand/BrandMark.js";
import { APP_BUILD, APP_VERSION, SUPPORT_REPOSITORY, createSupportBundle, downloadSupportBundle,
    environmentInfo, fetchBackendSupport, issueUrl, type BackendSupport } from "../../features/settings/supportDiagnostics.js";

export type AboutSettingsPanelProps = Record<string, never>;

export default function AboutSettingsPanel(props: AboutSettingsPanelProps) {
    void props;
    useLocale();
    const modifier = shortcutModifier();
    const [backend, setBackend] = useState<BackendSupport | null>(null);
    const [checking, setChecking] = useState(true);
    const [minutes, setMinutes] = useState(15);
    const [exporting, setExporting] = useState(false);
    const [feedback, setFeedback] = useState<"copied" | "copyFailed" | "exported" | "partial" | "exportFailed" | null>(null);
    const [manualCopy, setManualCopy] = useState("");
    useEffect(() => {
        const controller = new AbortController();
        void fetchBackendSupport(15, controller.signal).then(value => { if (!controller.signal.aborted) setBackend(value); }).catch(() => {
            if (!controller.signal.aborted) setBackend(null);
        }).finally(() => { if (!controller.signal.aborted) setChecking(false); });
        return () => controller.abort();
    }, []);
    const environment = environmentInfo(backend);
    const copyEnvironment = async () => {
        const text = JSON.stringify(environment, null, 2);
        try { await navigator.clipboard.writeText(text); setManualCopy(""); setFeedback("copied"); }
        catch { setManualCopy(text); setFeedback("copyFailed"); }
    };
    const exportDiagnostics = async () => {
        setExporting(true); setFeedback(null);
        try {
            const current = await fetchBackendSupport(minutes).catch(() => null);
            setBackend(current); setChecking(false);
            downloadSupportBundle(createSupportBundle(minutes, current));
            setFeedback(current ? "exported" : "partial");
        } catch { setFeedback("exportFailed"); }
        finally { setExporting(false); }
    };
    return <>
        <div className="st-group">
            <div className="st-about-header">
                <div className="st-about-logo"><BrandMark size={64} label="CandleScope" variant="full" /></div>
                <div className="st-about-name"><span>Candle</span><span className="st-about-name-accent">Scope</span></div>
                <div className="st-about-version">{APP_VERSION}</div>
                <div className="st-about-tagline">{t("settings.support.tagline")}</div>
            </div>
        </div>
        <section className="st-group st-support-card" aria-labelledby="support-heading">
            <h3 id="support-heading" className="st-group-title">{t("settings.support.title")}</h3>
            <p className="st-support-description">{t("settings.support.description")}</p>
            <div className="st-support-actions">
                <a className="st-btn st-btn-primary" href={issueUrl(environment)} target="_blank" rel="noopener noreferrer">{t("settings.support.issue")}</a>
                <button className="st-btn st-btn-secondary" onClick={() => void copyEnvironment()}>{t("settings.support.copy")}</button>
            </div>
            <p className="st-support-hint">{t("settings.support.issueHint")}</p>
            <details className="st-support-export">
                <summary>{t("settings.support.export")}</summary>
                <p className="st-support-description">{t("settings.support.exportHint")}</p>
                <p className="st-support-hint">{t("settings.support.privacy")}</p>
                <div className="st-support-actions">
                    <label>{t("settings.support.range")} <select value={minutes} disabled={exporting} onChange={event => setMinutes(Number(event.target.value))}>
                        {[5, 15, 60].map(value => <option key={value} value={value}>{t("settings.support.minutes", { count: value })}</option>)}
                    </select></label>
                    <button className="st-btn st-btn-primary" disabled={exporting} onClick={() => void exportDiagnostics()}>
                        {t(exporting ? "settings.support.exporting" : "settings.support.download")}
                    </button>
                </div>
            </details>
            <p className="st-support-hint" role="status" aria-live="polite">{feedback ? t(`settings.support.${feedback}`) : ""}</p>
            {manualCopy && <textarea className="st-support-manual" aria-label={t("settings.support.environment")} readOnly value={manualCopy} onFocus={event => event.target.select()} />}
        </section>
        <section className="st-group" aria-labelledby="support-environment">
            <h3 id="support-environment" className="st-group-title">{t("settings.support.environment")}</h3>
            <div className="st-about-stack">
                {[
                    [t("settings.support.version"), APP_VERSION],
                    [t("settings.support.build"), APP_BUILD],
                    [t("settings.support.backend"), checking ? t("settings.support.checking") : backend?.version ?? t("settings.support.unavailable")],
                    [t("settings.support.engine"), checking ? t("settings.support.checking") : t(backend?.data_engine === "active" ? "settings.support.active" : backend ? "settings.support.notReady" : "settings.support.unavailable")],
                    [t("settings.support.system"), `${environment.os} · ${environment.browser}`],
                ].map(([label, value]) => <div className="st-stack-item" key={label}><span className="st-stack-label">{label}</span><span className="st-stack-value">{value}</span></div>)}
            </div>
        </section>
        <section className="st-group" aria-labelledby="support-project">
            <h3 id="support-project" className="st-group-title">{t("settings.support.project")}</h3>
            <div className="st-support-links">
                {[
                    ["#readme", t("settings.support.docs")], ["/releases", t("settings.support.releases")],
                    ["", t("settings.support.source")], ["/blob/main/LICENSE", t("settings.support.license")],
                ].map(([path, label]) => <a key={label} href={`${SUPPORT_REPOSITORY}${path}`} target="_blank" rel="noopener noreferrer">{label}<span aria-hidden="true"> ↗</span></a>)}
            </div>
            <details className="st-support-export">
                <summary>{t("settings.support.help")}</summary>
                <p className="st-support-hint">{t("settings.support.credits")}</p>
                <div className="st-about-stack">
                    {[
                        [`${modifier} + K`, t("settings.about.shortcutSearch")],
                        ["/", t("settings.about.shortcutSearchSlash")],
                        ["Esc", t("settings.about.shortcutSearchClose")],
                        [`${modifier} + Z`, t("settings.about.shortcutWorkspaceUndo")],
                        [`${modifier} + Shift + Z`, t("settings.about.shortcutWorkspaceRedo")],
                    ].map(([keys, description]) => <div className="st-stack-item st-shortcut-item" key={keys}><kbd className="st-stack-value">{keys}</kbd><span className="st-stack-label">{description}</span></div>)}
                </div>
            </details>
        </section>
    </>;
}
