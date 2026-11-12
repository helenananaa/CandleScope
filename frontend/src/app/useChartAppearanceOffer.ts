import { useEffect } from "react";
import { notify } from "../components/ui/overlay/overlayApi.js";
import { t } from "../i18n/index.js";
import { takeChartAppearanceOfferCheck, type ChartTheme } from "../features/settings/chartAppearanceSettings.js";

/** Whether to offer `shared` as the app theme: every chart sets it on its own and the app uses another. */
export function shouldOfferChartTheme(shared: "dark" | "light" | null, appTheme: ChartTheme, alreadyChecked: boolean): shared is "dark" | "light" {
  return !alreadyChecked && shared !== null && appTheme !== shared;
}

/**
 * The old chart-scoped theme picker left many layouts with every chart set to the same theme on its
 * own. On the first launch with the chart menu, and only then, offer to make that the app theme and
 * let the charts follow it. A chart set on its own after that launch is the user's choice and never
 * triggers the offer.
 */
export function useChartAppearanceOffer({ ready, charts, shared, appTheme, adopt }: {
  ready: boolean;
  charts: number;
  shared: "dark" | "light" | null;
  appTheme: ChartTheme;
  adopt(theme: "dark" | "light"): void;
}): void {
  useEffect(() => {
    if (!ready) return;
    if (!shouldOfferChartTheme(shared, appTheme, takeChartAppearanceOfferCheck())) return;
    const label = t(shared === "light" ? "settings.appearance.theme.light" : "settings.appearance.theme.dark");
    notify({
      tone: "info",
      title: t(charts === 1 ? "chartAppearance.offerOne" : "chartAppearance.offer", { theme: label }),
      action: { label: t("chartAppearance.offerAction"), onClick: () => adopt(shared) },
      durationMs: 0,
    });
    // Only the first ready state decides; later changes are the user's own edits.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready]);
}
