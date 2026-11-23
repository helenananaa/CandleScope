import type { PluginPlatformRuntime } from "./pluginPlatformTypes.js";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { liveModeLabel } from "./pluginLabels.js";
import { ControlButton } from "../../components/ui/index.js";

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
          <ControlButton
            size="sm"
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
          </ControlButton>
        );
      })}
      {registries.commandPalette.length > 0 && (
        <ControlButton size="sm" data-plugin-command-palette onClick={runtime.actions.openPalette}>
          {t("plugin.host.commands")}
        </ControlButton>
      )}
      {legacyEnabled && [...registries.sidePanel, ...registries.bottomPanel].map((view) => (
        <ControlButton size="sm" key={view.id} data-plugin-view-button={view.id} onClick={() => runtime.actions.openView(view.id)}>
          {view.title}
        </ControlButton>
      ))}
      {legacyEnabled && registries.settings.map((settings) => (
        <ControlButton size="sm" key={settings.id} data-plugin-settings-button={settings.id} onClick={() => runtime.actions.openSettings(settings.id)}>
          {settings.title}
        </ControlButton>
      ))}
      {legacyEnabled && runtime.view.liveControl.mode !== "disabled" && (
        <ControlButton
          size="sm"
          data-live-control-button
          className={`live-control-toolbar live-control-${runtime.view.liveControl.mode}`}
          onClick={runtime.actions.openLiveControl}
        >
          {t("plugin.live.toolbar", { mode: liveModeLabel(runtime.view.liveControl.mode) })}
        </ControlButton>
      )}
    </div>
  );
}
