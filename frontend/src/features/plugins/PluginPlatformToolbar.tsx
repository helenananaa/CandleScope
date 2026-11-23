import type { PluginPlatformRuntime } from "./pluginPlatformTypes.js";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { liveModeLabel } from "./pluginLabels.js";

export default function PluginPlatformToolbar({ runtime }: { runtime: PluginPlatformRuntime }) {
  useLocale();
  const { catalog, registries, managementAvailable } = runtime.view;
  const legacyEnabled = catalog?.platform.enabled === true;
  const hasToolbarControls = registries.commandPalette.length > 0 || (legacyEnabled && (
    registries.topToolbar.length > 0
    || registries.sidePanel.length > 0
    || registries.bottomPanel.length > 0
    || registries.settings.length > 0
    || runtime.view.liveControl.mode !== "disabled"
  ));
  if (!hasToolbarControls) return null;
  return (
    <div className="plugin-toolbar" data-plugin-slot="topToolbar">
      {legacyEnabled && registries.topToolbar.map((command) => {
        const properties = command.configuration.inputSchema?.properties ?? {};
        const direct = Object.keys(properties).length === 0;
        return (
          <button
            type="button"
            key={command.id}
            data-plugin-command={command.id}
            disabled={!managementAvailable}
            title={managementAvailable ? command.title : t("plugin.host.managementRequired")}
            onClick={() => {
              if (direct) void runtime.actions.invokeCommand(command.id, {}).catch(() => undefined);
              else runtime.actions.openPalette();
            }}
          >
            {command.title}
          </button>
        );
      })}
      {registries.commandPalette.length > 0 && (
        <button type="button" data-plugin-command-palette onClick={runtime.actions.openPalette}>
          {t("plugin.host.commands")}
        </button>
      )}
      {legacyEnabled && [...registries.sidePanel, ...registries.bottomPanel].map((view) => (
        <button type="button" key={view.id} data-plugin-view-button={view.id} onClick={() => runtime.actions.openView(view.id)}>
          {view.title}
        </button>
      ))}
      {legacyEnabled && registries.settings.map((settings) => (
        <button type="button" key={settings.id} data-plugin-settings-button={settings.id} onClick={() => runtime.actions.openSettings(settings.id)}>
          {settings.title}
        </button>
      ))}
      {legacyEnabled && runtime.view.liveControl.mode !== "disabled" && (
        <button
          type="button"
          data-live-control-button
          className={`live-control-toolbar live-control-${runtime.view.liveControl.mode}`}
          onClick={runtime.actions.openLiveControl}
        >
          {t("plugin.live.toolbar", { mode: liveModeLabel(runtime.view.liveControl.mode) })}
        </button>
      )}
    </div>
  );
}
