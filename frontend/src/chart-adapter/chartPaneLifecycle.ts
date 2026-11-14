import type {
  ChartOptionsImpl,
  CrosshairOptions,
  DeepPartial,
  HorzScaleOptions,
  IChartApiBase,
  TickMarkType,
} from "lightweight-charts";
import type { ChartTime } from "./chartAdapterTypes.js";
import { CHART_CROSSHAIR_COLORS, CHART_FONT_FAMILY, CHART_THEME_COLORS, chartSchemeForBackground } from "./chartPalette.js";
import { getDateTimeLocale } from "../i18n/index.js";
import { getExtensionState } from "../features/extensions/state.js";

type AdapterTickMarkFormatter = (
  time: ChartTime,
  tickMarkType: TickMarkType,
  locale?: string,
) => string;

interface LocalizationBundle {
  localization?: {
    timeFormatter: (time: ChartTime) => string;
  };
  timeScale?: {
    tickMarkFormatter: AdapterTickMarkFormatter;
  };
}

interface PaneAppearanceOptions {
  theme?: string;
  inheritApplicationTheme?: boolean;
  customBg?: string;
  timezone?: string;
  interval?: string;
  timeFormatter?: (timeSeconds: number) => string;
  tickMarkFormatter?: (timeSeconds: number, tickMarkType: TickMarkType) => string;
  tickMarkMaxCharacterLength?: number;
}

function hasProperty<K extends PropertyKey>(
  value: object,
  key: K,
): value is object & Record<K, unknown> {
  return key in value;
}

function readUnknownProperty(value: object, key: PropertyKey): unknown {
  return hasProperty(value, key) ? value[key] : undefined;
}

type AdapterChartOptions = DeepPartial<ChartOptionsImpl<ChartTime>> & {
  timeScale?: DeepPartial<HorzScaleOptions> & {
    tickMarkFormatter?: AdapterTickMarkFormatter;
  };
};

function formatterSourceTime(value: unknown): number {
  const candidate = value !== null && typeof value === "object"
    ? readUnknownProperty(value, "sourceTime")
      ?? readUnknownProperty(value, "_ordinal_sourceTime")
      ?? value
    : value;
  const numeric = Number(candidate);
  return numeric;
}

export function buildLocalizationOptions(
  timezone = "Local",
  interval = "1h",
): LocalizationBundle {
  const timeZoneOpt = timezone && timezone !== "Local" ? timezone : undefined;
  try {
    const showSeconds = /^\d+s$/.test(String(interval));
    // "1M" is a month; minutes are lower-case "m".
    const showClock = !/^\d+([dDwW]|M)$/.test(String(interval));
    const tooltipFormatOptions: Intl.DateTimeFormatOptions = {
      year: "numeric", month: "2-digit", day: "2-digit",
      ...(showClock ? { hour: "2-digit", minute: "2-digit", hour12: false } : {}),
      ...(showSeconds ? { second: "2-digit" } : {}),
    };
    const datePartsOptions: Intl.DateTimeFormatOptions = {
      year: "numeric", month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
    };
    if (timeZoneOpt) {
      tooltipFormatOptions.timeZone = timeZoneOpt;
      datePartsOptions.timeZone = timeZoneOpt;
    }
    const dayTickOptions: Intl.DateTimeFormatOptions = { month: "short", day: "numeric" };
    const monthTickOptions: Intl.DateTimeFormatOptions = { year: "numeric", month: "short" };
    if (timeZoneOpt) {
      dayTickOptions.timeZone = timeZoneOpt;
      monthTickOptions.timeZone = timeZoneOpt;
    }
    let formatterLocale = "";
    let tooltipFormatter: Intl.DateTimeFormat;
    let partsFormatter: Intl.DateTimeFormat;
    let dayTickFormatter: Intl.DateTimeFormat;
    let monthTickFormatter: Intl.DateTimeFormat;
    const formatters = () => {
      const locale = getDateTimeLocale();
      if (locale !== formatterLocale) {
        formatterLocale = locale;
        tooltipFormatter = new Intl.DateTimeFormat(locale, tooltipFormatOptions);
        partsFormatter = new Intl.DateTimeFormat(locale, datePartsOptions);
        dayTickFormatter = new Intl.DateTimeFormat(locale, dayTickOptions);
        monthTickFormatter = new Intl.DateTimeFormat(locale, monthTickOptions);
      }
      return { tooltipFormatter, partsFormatter, dayTickFormatter, monthTickFormatter };
    };

    return {
      localization: {
        timeFormatter: (ts: ChartTime) => formatters().tooltipFormatter.format(
          new Date(formatterSourceTime(ts) * 1000),
        ),
      },
      timeScale: {
        tickMarkFormatter: (ts: ChartTime, tickMarkType: TickMarkType) => {
          const parts = formatters().partsFormatter.formatToParts(
            new Date(formatterSourceTime(ts) * 1000),
          );
          const get = (type: Intl.DateTimeFormatPartTypes): string => (
            parts.find((part) => part.type === type)?.value || ""
          );
          const year = get("year");
          const month = get("month");
          // CJK locales return a numeric month ("8"), which would read as "15 8";
          // let the locale write its own short date ("8月15日", "2026年8月") instead.
          if (/^\d+$/.test(month)) {
            const date = new Date(formatterSourceTime(ts) * 1000);
            const type = Number(tickMarkType);
            if (type === 1) return formatters().monthTickFormatter.format(date);
            if (type === 2 || type > 4) return formatters().dayTickFormatter.format(date);
          }
          const day = get("day");
          const hour = get("hour");
          const min = get("minute");
          const sec = get("second");

          switch (Number(tickMarkType)) {
            case 0:
              return year;
            case 1:
              return `${month} '${year.slice(-2)}`;
            case 2:
              return `${day} ${month}`;
            case 3:
              return showSeconds ? `${hour}:${min}:${sec}` : `${hour}:${min}`;
            case 4:
              return `${hour}:${min}:${sec}`;
            default:
              return `${day} ${month}`;
          }
        },
      },
    };
  } catch {
    return {};
  }
}

export function buildCrosshairOptions(visible = true): DeepPartial<CrosshairOptions> {
  return {
    mode: 0,
    vertLine: {
      color: CHART_CROSSHAIR_COLORS.line, width: 1, style: 2,
      labelBackgroundColor: CHART_CROSSHAIR_COLORS.label,
      visible,
      labelVisible: visible,
    },
    horzLine: {
      color: CHART_CROSSHAIR_COLORS.line, width: 1, style: 2,
      labelBackgroundColor: CHART_CROSSHAIR_COLORS.label,
      visible,
      labelVisible: visible,
    },
  };
}

export function getPaneThemeColors({ theme, customBg, inheritApplicationTheme = true }: PaneAppearanceOptions): {
  bgColor: string;
  textColor: string;
  gridColor: string;
  borderColor: string;
} {
  const extension = inheritApplicationTheme ? getExtensionState().theme : null;
  const tokens = extension?.tokens;
  theme = extension?.base ?? theme;
  const customBackground = theme === "custom" && customBg ? customBg : null;
  // Text and grid follow the background actually shown, so a light custom background stays readable.
  const scheme = customBackground ? chartSchemeForBackground(customBackground) : theme === "light" ? "light" : "dark";
  const colors = CHART_THEME_COLORS[scheme];
  return {
    bgColor: tokens?.["bg-primary"] ?? customBackground ?? colors.background,
    textColor: tokens?.["text-secondary"] ?? colors.text,
    gridColor: tokens?.["border-color"] ?? colors.grid,
    borderColor: tokens?.["border-color"] ?? colors.border,
  };
}

/** DOM legends and pane controls share the canvas palette, scoped to one chart. */
export function chartPaneCssVariables(options: PaneAppearanceOptions & {
  upColor: string; downColor: string;
}): Record<`--${string}`, string> {
  const colors = getPaneThemeColors(options);
  return {
    "--text-up": options.upColor,
    "--text-down": options.downColor,
    ...(options.inheritApplicationTheme === false ? {
      "--text-primary": colors.textColor,
      "--text-secondary": colors.textColor,
      "--text-muted": colors.textColor,
      "--bg-primary": colors.bgColor,
      "--bg-secondary": colors.bgColor,
      "--surface-0": colors.bgColor,
      "--surface-1": colors.bgColor,
      "--surface-2": colors.bgColor,
      "--surface-3": colors.bgColor,
      "--border-color": colors.borderColor,
    } : {}),
  };
}

export function buildChartPaneOptions({
  container,
  theme,
  inheritApplicationTheme = true,
  customBg,
  timezone,
  interval,
  showTimeScale,
  timeFormatter,
  tickMarkFormatter,
  tickMarkMaxCharacterLength,
}: PaneAppearanceOptions & {
  container: HTMLElement;
  showTimeScale?: boolean;
}): AdapterChartOptions {
  const loc = buildLocalizationOptions(timezone, interval);
  const { bgColor, textColor, gridColor, borderColor } = getPaneThemeColors({
    inheritApplicationTheme,
    ...(theme !== undefined ? { theme } : {}),
    ...(customBg !== undefined ? { customBg } : {}),
  });

  return {
    width: container.clientWidth,
    height: container.clientHeight,
    autoSize: true,
    layout: {
      background: { color: bgColor },
      textColor,
      fontFamily: CHART_FONT_FAMILY,
      fontSize: 12,
      attributionLogo: false,
    },
    grid: {
      vertLines: { color: gridColor },
      horzLines: { color: gridColor },
    },
    crosshair: buildCrosshairOptions(true),
    rightPriceScale: {
      alignLabels: false,
      entireTextOnly: true,
      borderColor,
      scaleMargins: { top: 0.05, bottom: 0.05 },
      autoScale: true,
      minimumWidth: 80,
    },
    ...(timeFormatter
      ? { localization: { timeFormatter: (time: ChartTime) => timeFormatter(formatterSourceTime(time)) } }
      : loc.localization ? { localization: loc.localization } : {}),
    timeScale: {
      borderColor,
      timeVisible: true,
      secondsVisible: false,
      rightOffset: 5,
      barSpacing: 8,
      ...(showTimeScale !== undefined ? { visible: showTimeScale } : {}),
      ...(tickMarkMaxCharacterLength !== undefined
        ? { tickMarkMaxCharacterLength }
        : {}),
      ...(tickMarkFormatter
        ? { tickMarkFormatter: (time: ChartTime, type: TickMarkType) => tickMarkFormatter(formatterSourceTime(time), type) }
        : loc.timeScale ? { tickMarkFormatter: loc.timeScale.tickMarkFormatter } : {}),
    },
    handleScroll: { vertTouchDrag: false },
  };
}

export function applyChartPaneAppearance(
  chart: IChartApiBase<ChartTime>,
  {
    theme,
    inheritApplicationTheme = true,
    customBg,
    timezone,
    interval,
    timeFormatter,
    tickMarkFormatter,
    tickMarkMaxCharacterLength,
  }: PaneAppearanceOptions,
): void {
  const loc = buildLocalizationOptions(timezone, interval);
  const { bgColor, textColor, gridColor, borderColor } = getPaneThemeColors({
    inheritApplicationTheme,
    ...(theme !== undefined ? { theme } : {}),
    ...(customBg !== undefined ? { customBg } : {}),
  });
  const appearanceOptions: AdapterChartOptions = {
    layout: { background: { color: bgColor }, textColor },
    grid: { vertLines: { color: gridColor }, horzLines: { color: gridColor } },
    rightPriceScale: { borderColor },
    timeScale: {
      borderColor,
      ...(tickMarkMaxCharacterLength !== undefined
        ? { tickMarkMaxCharacterLength }
        : {}),
      ...(tickMarkFormatter
        ? { tickMarkFormatter: (time: ChartTime, type: TickMarkType) => tickMarkFormatter(formatterSourceTime(time), type) }
        : loc.timeScale ? { tickMarkFormatter: loc.timeScale.tickMarkFormatter } : {}),
    },
    ...(timeFormatter
      ? { localization: { timeFormatter: (time: ChartTime) => timeFormatter(formatterSourceTime(time)) } }
      : loc.localization ? { localization: loc.localization } : {}),
  };
  chart.applyOptions(appearanceOptions);
}
