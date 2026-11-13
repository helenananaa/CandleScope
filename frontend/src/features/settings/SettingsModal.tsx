import { IconButton } from "../../components/ui/Button.js";
import { OverlayLayer } from "../../components/ui/Overlays.js";
import { confirmAction } from "../../components/ui/overlay/overlayApi.js";
import { useCallback, useId, useRef, useState } from 'react';
import DataWorkbenchModal from '../data-workbench/DataWorkbenchModal.js';
import { t } from '../../i18n/index.js';
import { useLocale } from '../../i18n/useLocale.js';
import SettingsPanelHost from './SettingsPanelHost.js';
import { Icon } from '../../components/icons/Icon.js';
import { buildSettingsPanelViewModel } from './settingsPanelViewModel.js';
import { SETTINGS_CATEGORIES, resolveSettingsTab } from './settingsTabRegistry.js';
import { useSettingsRuntime } from './useSettingsRuntime.js';
import { useControlCommands } from '../app-control/useControlCommands.js';
import { maintenanceCommands } from '../app-control/maintenanceCommands.js';
import { command } from '../app-control/commandRegistry.js';
import { bool, choice, empty, object } from '../app-control/commandSchema.js';
import type { MouseEvent } from 'react';
import type { PluginPlatformRuntime } from '../plugins/pluginPlatformTypes.js';
import type { SettingsCategory } from './settingsTypes.js';
import type { UseSettingsRuntimeOptions } from './useSettingsRuntime.js';

export interface SettingsModalProps extends UseSettingsRuntimeOptions {
    plugins?: PluginPlatformRuntime;
    allowedCategories?: readonly SettingsCategory[];
    backendFeaturesEnabled?: boolean;
    dataWorkbenchEnabled?: boolean;
    onClose(): void;
}

/**
 * Settings: one dialog with categories on the left. Changes apply as they are made; the
 * network proxy is the one form with its own 保存, and closing with unsaved proxy edits asks first.
 */
export default function SettingsModal({
    isOpen,
    onClose,
    plugins,
    allowedCategories = SETTINGS_CATEGORIES.map((category) => category.key),
    backendFeaturesEnabled = true,
    dataWorkbenchEnabled = true,
    appearanceScope = "application",
    appearanceTargets,
    settings,
    onUpdate,
    currentSymbol = '',
    currentMarketType = 'spot',
    currentExchange = 'binance',
    watchlists = [],
    chartDataCacheDiagnostics = null,
    trimChartDataCacheEntries = null,
}: SettingsModalProps) {
    const [activeCategory, setActiveCategory] = useState<SettingsCategory>('appearance');
    // A plugin install in progress: Settings stays open until it finishes.
    const [pluginBusy, setPluginBusy] = useState(false);
    const [dataWorkbenchOpen, setDataWorkbenchOpen] = useState(false);
    useLocale();
    const settingsRuntime = useSettingsRuntime({
        isOpen,
        settings,
        onUpdate,
        appearanceScope,
        ...(appearanceTargets ? { appearanceTargets } : {}),
        currentSymbol,
        currentMarketType,
        currentExchange,
        watchlists,
        chartDataCacheDiagnostics,
        trimChartDataCacheEntries,
    });
    const { view, actions } = settingsRuntime;
    const proxyDirty = view.proxy.proxyDirty;
    // The overlay layer moves focus to the panel, returns it on close and handles Escape.
    // The data workbench is its own layer above this one.
    const panelRef = useRef<HTMLDivElement>(null);
    // Instance identity allows several cells to open settings for the same symbol.
    const controlId = useId();
    const requestClose = useCallback(() => {
        if (pluginBusy) return;
        if (!proxyDirty) { onClose(); return; }
        void confirmAction({
            title: t("settings.unsaved.title"),
            message: t("settings.unsaved.message"),
            confirmLabel: t("settings.unsaved.discard"),
            tone: "danger",
        }).then((discard) => { if (discard) onClose(); });
    }, [pluginBusy, proxyDirty, onClose]);
    useControlCommands(() => maintenanceCommands(controlId, settingsRuntime, backendFeaturesEnabled), isOpen);
    useControlCommands(() => ({ id: `settings-panel:${controlId}`, title: "Settings categories and tools", context: () => ({ activeCategory, dataWorkbenchOpen }), snapshot: () => ({ activeCategory, allowedCategories, backendFeaturesEnabled, dataWorkbenchEnabled, dataWorkbenchOpen }), commands: [
        command("category", "Select an available settings category.", object({ category: choice(["appearance", "network", "exchanges", "data", "plugins", "about"]) }), ({ category }) => {
            if (!allowedCategories.includes(category) || (!backendFeaturesEnabled && category !== "appearance" && category !== "about")) throw new Error("CATEGORY_UNAVAILABLE");
            setActiveCategory(category);
        }),
        command("dataWorkbench", "Open/close the data workbench.", object({ open: bool }), ({ open }) => setDataWorkbenchOpen(open), { available: () => dataWorkbenchEnabled && backendFeaturesEnabled }),
        command("close", "Close settings.", empty, () => onClose()),
    ] }), isOpen);

    if (!isOpen) return null;

    const panelModel = buildSettingsPanelViewModel({ view, actions });
    const visibleCategories = SETTINGS_CATEGORIES.filter((category) => (
        allowedCategories.includes(category.key)
        && (backendFeaturesEnabled || category.key === "appearance" || category.key === "about")
    ));
    const resolvedActiveCategory = visibleCategories.some(
        (category) => category.key === activeCategory,
    ) ? activeCategory : visibleCategories[0]?.key ?? "appearance";
    const activeCatObj = resolveSettingsTab(resolvedActiveCategory);

    return (
        <>
            <OverlayLayer kind="modal" onClose={requestClose} closeOnEscape={!pluginBusy} initialFocusRef={panelRef}>
                <div className="st-overlay" onClick={requestClose}>
                    <div
                        ref={panelRef}
                        className="st-panel"
                        role="dialog"
                        aria-modal="true"
                        aria-labelledby="settings-dialog-title"
                        tabIndex={-1}
                        onClick={(event: MouseEvent<HTMLDivElement>) => event.stopPropagation()}
                    >
                        <nav className="st-sidebar" aria-labelledby="settings-dialog-title">
                            <div className="st-sidebar-title" id="settings-dialog-title">{t("settings.title")}</div>
                            <div className="st-sidebar-nav">
                                {visibleCategories.map(cat => (
                                    <button
                                        key={cat.key}
                                        type="button"
                                        className={`st-nav-item ${resolvedActiveCategory === cat.key ? 'active' : ''}`}
                                        aria-current={resolvedActiveCategory === cat.key ? 'page' : undefined}
                                        disabled={pluginBusy && cat.key !== resolvedActiveCategory}
                                        onClick={() => setActiveCategory(cat.key)}
                                    >
                                        <span className="st-nav-icon" aria-hidden="true"><Icon name={cat.icon} /></span>
                                        <span className="st-nav-label">{t(cat.labelKey)}</span>
                                        {cat.key === "network" && proxyDirty && (
                                            <span className="st-nav-dirty" title={t("settings.unsaved.badge")}>
                                                <span className="ui-visually-hidden">{t("settings.unsaved.badge")}</span>
                                            </span>
                                        )}
                                    </button>
                                ))}
                            </div>
                        </nav>

                        <main className="st-content" data-settings-category={resolvedActiveCategory}>
                            <div className="st-content-header">
                                <h2 className="st-content-title">
                                    <span className="st-content-title-icon" aria-hidden="true"><Icon name={activeCatObj.icon} size={20} /></span>
                                    {t(activeCatObj.labelKey)}
                                </h2>
                                <IconButton label={t("settings.close")} icon={<Icon name="close" size={16} />} disabled={pluginBusy} onClick={requestClose} />
                            </div>
                            <div className="st-content-body">
                                <SettingsPanelHost
                                    activeCategory={resolvedActiveCategory}
                                    onOpenDataWorkbench={() => {
                                        if (dataWorkbenchEnabled) setDataWorkbenchOpen(true);
                                    }}
                                    onPluginBusyChange={setPluginBusy}
                                    panelModel={panelModel}
                                    plugins={plugins}
                                />
                            </div>
                        </main>
                    </div>
                </div>
            </OverlayLayer>
            {dataWorkbenchEnabled && <DataWorkbenchModal
                currentExchange={currentExchange}
                currentMarketType={currentMarketType}
                currentSymbol={currentSymbol}
                isOpen={dataWorkbenchOpen}
                onClose={() => setDataWorkbenchOpen(false)}
            />}
        </>
    );
}
