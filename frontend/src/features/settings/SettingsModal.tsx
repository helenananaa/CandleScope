import { useCallback, useEffect, useRef, useState } from 'react';
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
        currentSymbol,
        currentMarketType,
        currentExchange,
        watchlists,
        chartDataCacheDiagnostics,
        trimChartDataCacheEntries,
    });
  const { view, actions } = settingsRuntime;
    const panelRef = useRef<HTMLDivElement>(null);
    const nestedOpen = pluginCenterOpen || dataWorkbenchOpen;

    // Move focus into the dialog on open and give it back to the opener on close.
    useEffect(() => {
        if (!isOpen) return undefined;
        const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        panelRef.current?.focus();
        return () => { opener?.focus(); };
    }, [isOpen]);

    // Escape closes Settings; nested surfaces handle their own Escape first.
    useEffect(() => {
        if (!isOpen || nestedOpen) return undefined;
        const onKeyDown = (event: KeyboardEvent) => {
            if (event.key !== 'Escape' || event.defaultPrevented) return;
            event.preventDefault();
            onClose();
        };
        window.addEventListener('keydown', onKeyDown);
        return () => window.removeEventListener('keydown', onKeyDown);
    }, [isOpen, nestedOpen, onClose]);

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
                        <button className="st-btn st-btn-primary st-btn-close" onClick={onClose}>
                            {t("settings.saveAndClose")}
                        </button>
                    </div>
                </nav>

                {/* Content */}
                <main className="st-content">
                    <div className="st-content-header">
                        <h2 className="st-content-title">
                            <span className="st-content-title-icon" aria-hidden="true"><Icon name={activeCatObj.icon} size={20} /></span>
                            {t(activeCatObj.labelKey)}
                        </h2>
                        <button className="st-close-x" aria-label={t("settings.close")} onClick={onClose}>✕</button>
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
