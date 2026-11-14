// Chart canvas colours for the Graphite themes (DESIGN.md). The canvas cannot read CSS
// variables for a theme that differs from the page, so the values live here and
// scripts/design-tokens.test.mjs keeps them in step with tokens.css.

export interface ChartSchemeColors {
  readonly background: string;
  readonly text: string;
  readonly grid: string;
  readonly border: string;
}

export const CHART_THEME_COLORS: Readonly<Record<"dark" | "light", ChartSchemeColors>> = Object.freeze({
  // Grid and border are translucent so they also suit any custom background of the same scheme.
  dark: { background: "#0d0e10", text: "#a6a9b0", grid: "rgba(255, 255, 255, 0.05)", border: "rgba(255, 255, 255, 0.09)" },
  light: { background: "#ffffff", text: "#4a4d55", grid: "rgba(0, 0, 0, 0.06)", border: "rgba(0, 0, 0, 0.1)" },
});

export const CHART_CROSSHAIR_COLORS = Object.freeze({
  line: "rgba(20, 115, 230, 0.45)",
  label: "#1473e6",
});

export const CHART_FONT_FAMILY = "'IBM Plex Sans', 'PingFang SC', 'Microsoft YaHei', sans-serif";

function relativeLuminance(hex: string): number | null {
  const match = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(hex.trim());
  if (!match?.[1]) return null;
  const digits = match[1].length === 3 ? [...match[1]].map((digit) => digit + digit).join("") : match[1];
  const [r, g, b] = [0, 2, 4].map((offset) => {
    const channel = parseInt(digits.slice(offset, offset + 2), 16) / 255;
    return channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

/**
 * Which foreground set reads on a background. 0.179 is where black and white text have
 * equal contrast, so light backgrounds get dark text and the reverse.
 */
export function chartSchemeForBackground(background: string): "dark" | "light" {
  const luminance = relativeLuminance(background);
  return luminance !== null && luminance > 0.179 ? "light" : "dark";
}
