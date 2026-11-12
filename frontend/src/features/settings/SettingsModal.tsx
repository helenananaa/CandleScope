import { Button } from "../../components/ui/Button.js";
import { OverlayLayer } from "../../components/ui/Overlays.js";
import { useCallback, useId, useRef, useState } from 'react';
import { PluginSettingsPanel } from '../plugins/PluginCenter.js';
import DataWorkbenchModal from '../data-workbench/DataWorkbenchModal.js';
import { t } from '../../i18n/index.js';
import { useLocale } from '../../i18n/useLocale.js';
import SettingsPanelHost from './SettingsPanelHost.js';
import { Icon } from '../../components/icons/Icon.js';
import SettingsModalStyles from './SettingsModalStyles.js';
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
    const [pluginCenterOpen, setPluginCenterOpen] = useState(false);
    const closePluginCenter = useCallback(() => setPluginCenterOpen(false), []);
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
    // The overlay layer moves focus to the panel, returns it on close and handles Escape.
    // Plugin center and the data workbench are their own layers above this one.
    const panelRef = useRef<HTMLDivElement>(null);
  // Instance identity allows several cells to open settings for the same symbol.
  const controlId = useId();
  useControlCommands(() => maintenanceCommands(controlId, settingsRuntime, backendFeaturesEnabled), isOpen);
  useControlCommands(() => ({ id: `settings-panel:${controlId}`, title: "Settings categories and tools", context: () => ({ activeCategory, pluginCenterOpen, dataWorkbenchOpen }), snapshot: () => ({ activeCategory, allowedCategories, backendFeaturesEnabled, dataWorkbenchEnabled, pluginCenterOpen, dataWorkbenchOpen }), commands: [
    command("category", "Select an available settings category.", object({ category: choice(["appearance", "network", "exchanges", "data", "plugins", "about"]) }), ({ category }) => {
      if (!allowedCategories.includes(category) || (!backendFeaturesEnabled && category !== "appearance" && category !== "about")) throw new Error("CATEGORY_UNAVAILABLE");
      if (category === "plugins" && plugins) setPluginCenterOpen(true); else setActiveCategory(category);
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
        {/* Hidden, not unmounted, while the plugin center is open so 返回 restores this state */}
        <OverlayLayer kind="modal" onClose={onClose} initialFocusRef={panelRef}>
        <div className="st-overlay" hidden={pluginCenterOpen} inert={pluginCenterOpen} onClick={onClose}>
            <div
                ref={panelRef}
                className="st-panel"
                role="dialog"
                aria-modal="true"
                aria-labelledby="settings-dialog-title"
                tabIndex={-1}
                onClick={(event: MouseEvent<HTMLDivElement>) => event.stopPropagation()}
            >
                {/* Sidebar */}
                <nav className="st-sidebar">
                    <div className="st-sidebar-title" id="settings-dialog-title">{t("settings.title")}</div>
                    <div className="st-sidebar-nav">
                        {visibleCategories.map(cat => (
                            <button
                                key={cat.key}
                                className={`st-nav-item ${activeCategory === cat.key ? 'active' : ''}`}
                                aria-current={activeCategory === cat.key ? 'page' : undefined}
                                onClick={() => { if (cat.key === "plugins" && plugins) setPluginCenterOpen(true); else setActiveCategory(cat.key); }}
                            >
                                <span className="st-nav-icon" aria-hidden="true"><Icon name={cat.icon} /></span>
                                <span className="st-nav-label">{t(cat.labelKey)}</span>
                            </button>
                        ))}
                    </div>
                    <div className="st-sidebar-footer">
                        <Button variant="primary" fullWidth onClick={onClose}>
                            {t("settings.saveAndClose")}
                        </Button>
                    </div>
                </nav>

                {/* Content */}
                <main className="st-content">
                    <div className="st-content-header">
                        <h2 className="st-content-title">
                            <span className="st-content-title-icon" aria-hidden="true"><Icon name={activeCatObj.icon} size={20} /></span>
                            {t(activeCatObj.labelKey)}
                        </h2>
                        <button className="st-close-x" aria-label={t("settings.close")} onClick={onClose}><Icon name="close" size={14} /></button>
                    </div>
                    <div className="st-content-body">
                        <SettingsPanelHost
                            activeCategory={resolvedActiveCategory}
                            onOpenDataWorkbench={() => {
                              if (dataWorkbenchEnabled) setDataWorkbenchOpen(true);
                            }}
                            panelModel={panelModel}
                            plugins={plugins}
                        />
                    </div>
                </main>
            </div>
            <SettingsModalStyles />
        </div>
        </OverlayLayer>
        {pluginCenterOpen && plugins && <PluginSettingsPanel runtime={plugins} onClose={closePluginCenter} />}
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
