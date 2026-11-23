import { useRef } from "react";
import { IconButton } from "../components/ui/Button.js";
import { OverlayLayer } from "../components/ui/Overlays.js";
import type { MouseEvent } from "react";
import ChartAppearancePanel from "../components/settings/ChartAppearancePanel.js";
import { Icon } from "../components/icons/Icon.js";
import { t } from "../i18n/index.js";
import { useLocale } from "../i18n/useLocale.js";
import type { ChartSettingsRuntime } from "../features/settings/chartAppearanceSettings.js";

/**
 * Appearance-only Settings for pages that must not load the live market runtime
 * (the replay entry). Same look and keyboard behaviour as the full Settings dialog.
 */
export default function PageSettingsDialog({
  runtime,
  onClose,
}: {
  runtime: ChartSettingsRuntime;
  onClose(): void;
}) {
  useLocale();
  // The overlay layer moves focus to the panel, returns it on close and handles Escape.
  const panelRef = useRef<HTMLDivElement>(null);

  return (
    <OverlayLayer kind="modal" onClose={onClose} initialFocusRef={panelRef}>
    <div className="st-overlay" onClick={onClose}>
      <div
        ref={panelRef}
        className="st-panel st-panel-single"
        role="dialog"
        aria-modal="true"
        aria-labelledby="page-settings-title"
        tabIndex={-1}
        onClick={(event: MouseEvent<HTMLDivElement>) => event.stopPropagation()}
      >
        <main className="st-content">
          <div className="st-content-header">
            <h2 className="st-content-title" id="page-settings-title">
              <span className="st-content-title-icon" aria-hidden="true"><Icon name="palette" size={20} /></span>
              {t("settings.title")}
            </h2>
            <IconButton label={t("settings.close")} icon={<Icon name="close" size={16} />} onClick={onClose} />
          </div>
          <div className="st-content-body">
            <ChartAppearancePanel appearanceScope={runtime.appearanceScope ?? "application"} {...(runtime.appearanceTargets ? { appearanceTargets: runtime.appearanceTargets } : {})} settings={runtime.settings} onUpdate={runtime.setSettings} />
          </div>
        </main>
      </div>
    </div>
    </OverlayLayer>
  );
}
