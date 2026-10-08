import assert from "node:assert/strict";
import test from "node:test";

import {
  buildChartPaneOptions,
  buildLocalizationOptions,
} from "../chartPaneLifecycle.js";
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
