import assert from "node:assert/strict";
import test from "node:test";

import {
  buildChartPaneOptions,
  applyChartPaneAppearance,
  getPaneThemeColors,
  chartPaneCssVariables,
  buildLocalizationOptions,
} from "../chartPaneLifecycle.js";
import { getExtensionState, publishExtensions } from "../../features/extensions/state.js";
import { structuralMock } from "../../test/testHelpers.js";
import { getLocale, setLocale } from "../../i18n/locale.js";

test("localization formatters resolve public and internal ordinal source time", () => {
  const options = buildLocalizationOptions("UTC", "1h");
  const formatters = structuralMock<{
    localization: { timeFormatter: (time: unknown) => string };
    timeScale: { tickMarkFormatter: (time: unknown, weight: number) => string };
  }>(options);
  const sourceTime = 1_700_000_000;
  const publicOrdinal = { order: 5, sourceTime, sourceOrdinal: 0 };
  const internalOrdinal = { _ordinal_order: 5, _ordinal_sourceTime: sourceTime };

  assert.equal(
    formatters.localization.timeFormatter(publicOrdinal),
    formatters.localization.timeFormatter(sourceTime),
  );
  assert.equal(
    formatters.localization.timeFormatter(internalOrdinal),
    formatters.localization.timeFormatter(sourceTime),
  );
  assert.equal(
    formatters.timeScale.tickMarkFormatter(publicOrdinal, 3),
    formatters.timeScale.tickMarkFormatter(sourceTime, 3),
  );
});

test("chart pane forwards the custom tick-label width budget", () => {
  const options = buildChartPaneOptions({
    container: structuralMock<HTMLElement>({
      clientWidth: 900,
      clientHeight: 500,
    }),
    tickMarkMaxCharacterLength: 12,
  });

  assert.equal(options.timeScale?.tickMarkMaxCharacterLength, 12);
});

test("CJK date ticks use the locale's own short date instead of day-number pairs", () => {
  const previous = getLocale();
  setLocale("zh-CN");
  try {
    const options = buildLocalizationOptions("UTC", "1h");
    const formatters = structuralMock<{
      localization: { timeFormatter: (time: unknown) => string };
      timeScale: { tickMarkFormatter: (time: unknown, weight: number) => string };
    }>(options);
    const aug15 = Date.UTC(2026, 7, 15, 2) / 1000;
    assert.equal(formatters.timeScale.tickMarkFormatter(aug15, 2), "8月15日");
    assert.equal(formatters.timeScale.tickMarkFormatter(aug15, 1), "2026年8月");
    assert.doesNotMatch(formatters.localization.timeFormatter(aug15), /:\d\d:\d\d/);
  } finally {
    setLocale(previous);
  }
});


test("explicit chart themes override extension tokens while inherited charts follow the application", () => {
  const previous = getExtensionState().theme;
  publishExtensions({ theme: { base: "dark", tokens: { "bg-primary": "#123456", "text-secondary": "#abcdef" } } });
  try {
    assert.equal(getPaneThemeColors({ theme: "light" }).bgColor, "#123456");
    const independent = { theme: "light", inheritApplicationTheme: false };
    assert.equal(getPaneThemeColors(independent).bgColor, "#ffffff");
    assert.equal(getPaneThemeColors(independent).textColor, "#1e293b");
    const options = buildChartPaneOptions({ ...independent,
      container: structuralMock<HTMLElement>({ clientWidth: 900, clientHeight: 500 }),
    });
    const background = options.layout?.background;
    assert.ok(background && "color" in background);
    assert.equal(background.color, "#ffffff");
    const applied: object[] = [];
    applyChartPaneAppearance(structuralMock({ applyOptions: (value: object) => applied.push(value) }), {
      theme: "custom", customBg: "#654321", inheritApplicationTheme: false,
    });
    assert.equal(structuralMock<{ layout: { background: { color: string } } }>(applied[0]!).layout.background.color, "#654321");
    assert.equal(getPaneThemeColors({ theme: "dark" }).bgColor, "#123456");
  } finally { publishExtensions({ theme: previous }); }
});


test("per-chart DOM legend colors match candles and explicit pane themes", () => {
  const palette = chartPaneCssVariables({ theme: "light", inheritApplicationTheme: false,
    upColor: "#ff0000", downColor: "#00ff00" });
  assert.equal(palette["--text-up"], "#ff0000");
  assert.equal(palette["--text-down"], "#00ff00");
  assert.equal(palette["--text-muted"], "#1e293b");
  assert.equal(palette["--surface-0"], "#ffffff");
  assert.deepEqual(chartPaneCssVariables({ theme: "dark", upColor: "#123456", downColor: "#654321" }), {
    "--text-up": "#123456", "--text-down": "#654321",
  });
});
