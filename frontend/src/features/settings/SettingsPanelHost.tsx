import { buttonClassName } from "../../components/ui/helpers.js";
import { Badge } from "../../components/ui/Display.js";
import { EmptyState } from "../../components/ui/EmptyState.js";
import { Button } from "../../components/ui/Button.js";
import { TabPanel, Tabs } from "../../components/ui/Choice.js";
import AiControlSettingsPanel from "../ai-control/AiControlSettingsPanel.js";
import { useId, useState } from "react";
import AboutSettingsPanel from "./panels/AboutSettingsPanel.js";
import CacheDiagnosticsPanel from "./panels/CacheDiagnosticsPanel.js";
import CacheLimitsPanel from "./panels/CacheLimitsPanel.js";
import ChartAppearancePanel from "./panels/ChartAppearancePanel.js";
import ExchangeSettingsPanel from "./panels/ExchangeSettingsPanel.js";
import ProxySettingsPanel from "./panels/ProxySettingsPanel.js";
import StorageMaintenancePanel from "./panels/StorageMaintenancePanel.js";
import { PluginSettingsPanel } from "../plugins/PluginPlatformSurfaces.js";
import type { PluginPlatformRuntime } from "../plugins/pluginPlatformTypes.js";
import type { SettingsCategory, SettingsPanelViewModel } from "./settingsTypes.js";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";

export interface SettingsPanelHostProps {
  activeCategory: SettingsCategory;
  panelModel: SettingsPanelViewModel;
  plugins?: PluginPlatformRuntime | undefined;
  onOpenDataWorkbench(): void;
  /** A plugin install is running; Settings must stay open until it ends. */
  onPluginBusyChange?(busy: boolean): void;
}

type DataView = "library" | "storage" | "maintenance";

export default function SettingsPanelHost({
  activeCategory,
  panelModel,
  plugins,
  onOpenDataWorkbench,
  onPluginBusyChange,
}: SettingsPanelHostProps) {
  useLocale();
  const [dataView, setDataView] = useState<DataView>("library");
  const dataTabsId = useId();
  switch (activeCategory) {
    case "appearance":
      return <ChartAppearancePanel {...panelModel.appearance} />;
    case "network":
      return <ProxySettingsPanel {...panelModel.network} />;
    case "exchanges":
      return <ExchangeSettingsPanel {...panelModel.exchanges} />;
    case "data":
      return (
        <div className="st-data">
          <Tabs<DataView> id={dataTabsId} label={t("settings.category.data")} value={dataView} onChange={setDataView} tabs={[
            { value: "library", label: t("ux.dataLibrary") },
            { value: "storage", label: t("ux.storage") },
            { value: "maintenance", label: t("settings.maint.title") },
          ]} />
          <TabPanel tabsId={dataTabsId} value={dataView} className="st-data-panel">
            {/* Hidden rather than unmounted, so each view keeps its state. */}
            <div hidden={dataView !== "library"}>
              <ul className="st-launch-list">
                <li className="st-launch-row">
                  <div className="st-launch-text">
                    <strong>{t("settings.data.libraryName")}</strong>
                    <span>{t("settings.data.libraryDesc")}</span>
                  </div>
                  <a className={buttonClassName({ variant: "primary" })} href="/strategy.html?action=import">{t("research.source.openLibrary")}</a>
                </li>
                <li className="st-launch-row">
                  <div className="st-launch-text">
                    <strong>{t("settings.workbench.name")} <Badge>{t("settings.workbench.readOnly")}</Badge></strong>
                    <span>{t("settings.workbench.summary")}</span>
                  </div>
                  <Button onClick={onOpenDataWorkbench}>{t("settings.workbench.open")}</Button>
                </li>
              </ul>
            </div>
            <div hidden={dataView !== "storage"}>
              <CacheDiagnosticsPanel {...panelModel.data.cacheDiagnostics} />
              <CacheLimitsPanel {...panelModel.data.cacheLimits} />
            </div>
            <div hidden={dataView !== "maintenance"}>
              <StorageMaintenancePanel {...panelModel.data.maintenance} />
            </div>
          </TabPanel>
        </div>
      );
    case "plugins":
      return plugins
        ? <PluginSettingsPanel runtime={plugins} {...(onPluginBusyChange ? { onBusyChange: onPluginBusyChange } : {})} />
        : <EmptyState title={t("settings.pluginsUnavailable")} />;
    case "ai":
      return <AiControlSettingsPanel />;
    case "about":
      return <AboutSettingsPanel />;
    default:
      return <ChartAppearancePanel {...panelModel.appearance} />;
  }
}
