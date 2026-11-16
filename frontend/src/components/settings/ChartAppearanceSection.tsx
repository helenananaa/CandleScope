import { Checkbox, SegmentedControl } from "../ui/index.js";
import type { AppearanceTargets, ChartAppearanceOverride, ChartTheme } from "../../features/settings/chartAppearanceSettings.js";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";

type OwnTheme = Extract<ChartTheme, "dark" | "light" | "custom">;

function effectiveScheme(theme: ChartTheme): "dark" | "light" {
  if (theme === "light") return "light";
  if (theme === "system" && typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: light)").matches) return "light";
  return "dark";
}

/**
 * A chart's own appearance, in its header menu: follow the app theme (the default), or its own
 * dark, light or custom background with optional up/down colours. The app theme never overrides it.
 */
export default function ChartAppearanceSection({ targets }: { targets: AppearanceTargets }) {
  useLocale();
  const { application, chart } = targets;
  const override = chart.override;
  const own = Object.keys(override).length > 0;
  const ownTheme: OwnTheme = override.theme === "light" || override.theme === "custom" ? override.theme : "dark";
  const ownColors = override.upColor !== undefined || override.downColor !== undefined;
  const set = (next: ChartAppearanceOverride) => chart.set(next);
  const linked = chart.linkedCharts ?? 0;
  return (
    <section className="chart-appearance-section" aria-label={t("chartAppearance.title")}>
      <h4>{t("chartAppearance.title")}</h4>
      <SegmentedControl
        size="sm"
        fullWidth
        label={t("chartAppearance.title")}
        value={own ? "own" : "follow"}
        onChange={(next) => {
          if (next === "follow") chart.set(null);
          else if (!own) set({ theme: effectiveScheme(application.theme) });
        }}
        options={[
          { value: "follow", label: t("settings.appearance.followApp") },
          { value: "own", label: t("settings.appearance.ownAppearance") },
        ]}
      />
      {own && (
        <>
          <SegmentedControl
            size="sm"
            fullWidth
            label={t("settings.appearance.themeTitle")}
            value={ownTheme}
            onChange={(theme) => set({
              ...override,
              theme,
              ...(theme === "custom" && !override.customBg ? { customBg: application.customBg } : {}),
            })}
            options={[
              { value: "dark", label: t("settings.appearance.theme.dark") },
              { value: "light", label: t("settings.appearance.theme.light") },
              { value: "custom", label: t("settings.appearance.theme.custom") },
            ]}
          />
          {ownTheme === "custom" && (
            <label className="chart-appearance-color">
              <span>{t("settings.appearance.customBg")}</span>
              <input type="color" value={override.customBg ?? application.customBg}
                onChange={(event) => set({ ...override, customBg: event.target.value })} />
            </label>
          )}
          <Checkbox
            label={t("chartAppearance.ownColors")}
            checked={ownColors}
            onChange={(event) => {
              const next: ChartAppearanceOverride = { ...override };
              if (event.target.checked) {
                next.upColor = application.upColor;
                next.downColor = application.downColor;
              } else {
                delete next.upColor;
                delete next.downColor;
              }
              set(next);
            }}
          />
          {ownColors && (
            <div className="chart-appearance-colors">
              <label className="chart-appearance-color">
                <span>{t("settings.appearance.upColor")}</span>
                <input type="color" value={override.upColor ?? application.upColor}
                  onChange={(event) => set({ ...override, upColor: event.target.value })} />
              </label>
              <label className="chart-appearance-color">
                <span>{t("settings.appearance.downColor")}</span>
                <input type="color" value={override.downColor ?? application.downColor}
                  onChange={(event) => set({ ...override, downColor: event.target.value })} />
              </label>
            </div>
          )}
        </>
      )}
      {linked > 0 && <p className="chart-appearance-note">{t("chartAppearance.linked", { count: linked })}</p>}
    </section>
  );
}
