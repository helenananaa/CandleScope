import { useEffect, useRef } from "react";
import type { MouseEvent } from "react";
import ChartAppearancePanel from "../components/settings/ChartAppearancePanel.js";
import { Icon } from "../components/icons/Icon.js";
import SettingsModalStyles from "../features/settings/SettingsModalStyles.js";
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
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    panelRef.current?.focus();
    return () => { opener?.focus(); };
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      event.preventDefault();
      onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => { window.removeEventListener("keydown", onKeyDown); };
  }, [onClose]);

  return (
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
            <button type="button" className="st-close-x" aria-label={t("settings.close")} onClick={onClose}>
              <Icon name="close" size={14} />
            </button>
          </div>
          <div className="st-content-body">
            <ChartAppearancePanel settings={runtime.settings} onUpdate={runtime.setSettings} />
          </div>
        </main>
      </div>
      <SettingsModalStyles />
    </div>
  );
}
