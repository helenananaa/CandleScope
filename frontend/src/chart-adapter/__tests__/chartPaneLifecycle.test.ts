import assert from "node:assert/strict";
import test from "node:test";

import { contrastRatio, parseColor } from "../legibleColor.js";
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
    assert.equal(getPaneThemeColors(independent).textColor, "#4a4d55");
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


test("per-chart DOM legend colors follow the candles and stay readable on the pane", () => {
  const readable = (color: string, background: string) => contrastRatio(parseColor(color)!, parseColor(background)!) >= 4.5;
  const palette = chartPaneCssVariables({ theme: "light", inheritApplicationTheme: false,
    upColor: "#ff0000", downColor: "#00ff00" });
  // Pure red and green are too light for a white pane; the legend gets darker shades of them.
  assert.match(palette["--text-up"]!, /^#[a-f0-9]{2}0000$/);
  assert.ok(readable(palette["--text-up"]!, "#ffffff"));
  assert.ok(readable(palette["--text-down"]!, "#ffffff"));
  assert.equal(palette["--text-muted"], "#4a4d55");
  assert.equal(palette["--surface-0"], "#ffffff");
  // Colours that already read on the dark pane are kept as chosen.
  assert.deepEqual(chartPaneCssVariables({ theme: "dark", upColor: "#22c55e", downColor: "#ef4444" }), {
    "--text-up": "#22c55e", "--text-down": "#ef4444",
  });
});


test("custom chart backgrounds pick readable text and grid colours", () => {
  const lightCustom = getPaneThemeColors({ theme: "custom", customBg: "#f4efe2", inheritApplicationTheme: false });
  assert.equal(lightCustom.bgColor, "#f4efe2");
  assert.equal(lightCustom.textColor, "#4a4d55");
  assert.equal(lightCustom.gridColor, "rgba(0, 0, 0, 0.06)");
  const darkCustom = getPaneThemeColors({ theme: "custom", customBg: "#102030", inheritApplicationTheme: false });
  assert.equal(darkCustom.textColor, "#a6a9b0");
  assert.equal(getPaneThemeColors({ theme: "dark", inheritApplicationTheme: false }).bgColor, "#0d0e10");
});
