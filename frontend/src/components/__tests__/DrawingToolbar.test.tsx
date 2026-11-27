import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { getLocale, setLocale, setLocaleAsync } from "../../i18n/index.js";
import DrawingToolbar from "../DrawingToolbar.js";

function buttonTag(html: string, attribute: string): string {
  return html.match(new RegExp(`<button[^>]*${attribute}[^>]*>`))?.[0] ?? "";
}

function renderInEnglish(element: React.ReactNode): string {
  const previousLocale = getLocale();
  try {
    setLocale("en");
    return renderToStaticMarkup(element);
  } finally {
    setLocale(previousLocale);
  }
}

test("drawing tool tips follow the six added interface languages", async () => {
  const previousLocale = getLocale();
  try {
    for (const [locale, eraser, text] of [
      ["de", "Radierer", "Textnotiz"],
      ["it", "Gomma", "Nota di testo"],
      ["id", "Penghapus", "Catatan teks"],
      ["tr", "Silgi", "Metin notu"],
      ["vi", "Tẩy", "Ghi chú văn bản"],
      ["pl", "Gumka", "Notatka tekstowa"],
    ] as const) {
      await setLocaleAsync(locale);
      const html = renderToStaticMarkup(
        <DrawingToolbar
          activeTool="cursor-crosshair"
          penColor="#f59e0b"
          penSize={2}
          onClearAll={() => {}}
          onToggleDrawingsHidden={() => {}}
          onPositionSizeChange={() => {}}
        />,
      );
      assert.ok(buttonTag(html, 'data-drawing-tool="eraser"').includes(`title="${eraser}"`));
      assert.ok(buttonTag(html, 'data-drawing-tool="text"').includes(`title="${text}"`));
      assert.doesNotMatch(buttonTag(html, 'data-drawing-tool="fibonacci"'), /right-click|double-click/);
    }
  } finally {
    setLocale(previousLocale);
  }
});

test("engine wait disables drawing tools without hiding chart, cursor, or export controls", () => {
  const html = renderInEnglish(
    <DrawingToolbar
      activeTool="cursor-crosshair"
      drawingInteractionReady={false}
      penColor="#f59e0b"
      penSize={2}
      selectedDrawing={{ id: "line-1", type: "line", color: "#f59e0b", lineWidth: 2 }}
      onClearAll={() => {}}
      onToggleDrawingsHidden={() => {}}
      onPositionSizeChange={() => {}}
    />,
  );

  assert.match(html, /data-drawing-toolbar-state="waiting-for-engine"/);
  assert.match(buttonTag(html, 'data-drawing-tool="pen"'), /disabled=""/);
  assert.doesNotMatch(buttonTag(html, 'data-chart-type="candlestick"'), /disabled=""/);
  assert.doesNotMatch(buttonTag(html, 'data-drawing-tool="cursor"'), /disabled=""/);
  assert.doesNotMatch(buttonTag(html, 'data-drawing-action="export"'), /disabled=""/);
  assert.doesNotMatch(buttonTag(html, 'title="Snap enabled'), /disabled=""/);
  assert.doesNotMatch(html, /title="Line color"/);
});

test("continuous drawing toggle exposes its selected state beside the snap toggle", () => {
  const html = renderInEnglish(
    <DrawingToolbar
      activeTool="line-segment"
      drawingContinuousEnabled
      penColor="#f59e0b"
      penSize={2}
      onClearAll={() => {}}
      onToggleDrawingsHidden={() => {}}
      onPositionSizeChange={() => {}}
    />,
  );

  const button = buttonTag(html, 'data-drawing-tool="continuous"');
  assert.match(button, /class="ui-icon-btn drawing-tool-btn"/);
  assert.match(button, /aria-pressed="true"/);
  assert.match(button, /title="Continuous drawing enabled; stay on the selected tool after completing a drawing"/);
});

test("auto-select defaults off and reflects an enabled preference beside continuous drawing", () => {
  for (const enabled of [false, true]) {
    const html = renderInEnglish(<DrawingToolbar activeTool="cursor-default" drawingAutoSelectEnabled={enabled}
      penColor="#f59e0b" penSize={2} onClearAll={() => {}} onToggleDrawingsHidden={() => {}} onPositionSizeChange={() => {}} />);
    const button = buttonTag(html, 'data-drawing-tool="auto-select"');
    assert.ok(button.includes('class="ui-icon-btn drawing-tool-btn"'));
    assert.ok(button.includes(`aria-pressed="${enabled}"`));
    assert.ok(button.includes(enabled ? "Auto-select enabled" : "Auto-select disabled"));
    assert.ok(html.indexOf('data-drawing-tool="continuous"') < html.indexOf('data-drawing-tool="auto-select"'));
  }
});

test("source range variants keep their own toolbar identity and translated title", () => {
  for (const [tool, label] of [["measure-price", "Price range"], ["measure-time", "Time range"], ["measure-price-time", "Price and time range"]] as const) {
    const html = renderInEnglish(<DrawingToolbar activeTool={tool} penColor="#f59e0b" penSize={2}
      onClearAll={() => {}} onToggleDrawingsHidden={() => {}} onPositionSizeChange={() => {}} />);
    assert.ok(buttonTag(html, `data-drawing-tool="${tool}"`).includes(label));
  }
});

test("arrow and parallel channel variants keep their own toolbar identity and translated title", () => {
  for (const [tool, label] of [["line-arrow", "Arrow"], ["channel-parallel", "Parallel channel"]] as const) {
    const html = renderInEnglish(<DrawingToolbar activeTool={tool} penColor="#f59e0b" penSize={2}
      onClearAll={() => {}} onToggleDrawingsHidden={() => {}} onPositionSizeChange={() => {}} />);
    assert.ok(buttonTag(html, `data-drawing-tool="${tool}"`).includes(label));
  }
});

test("calculated drawing variants share one toolbar button with their own identity and title", () => {
  for (const [tool, label] of [
    ["fib-extension", "Fib extension"],
    ["anchored-vwap", "Anchored VWAP"],
    ["volume-profile", "Fixed range volume profile"],
    ["regression-channel", "Regression channel"],
  ] as const) {
    const html = renderInEnglish(<DrawingToolbar activeTool={tool} penColor="#f59e0b" penSize={2}
      onClearAll={() => {}} onToggleDrawingsHidden={() => {}} onPositionSizeChange={() => {}} />);
    const button = buttonTag(html, `data-drawing-tool="${tool}"`);
    assert.ok(button.includes(`${label} (right-click or double-click for other calculated drawings)`), tool);
    assert.doesNotMatch(button, /disabled=""/);
  }
  const idle = renderInEnglish(<DrawingToolbar activeTool={null} penColor="#f59e0b" penSize={2}
    onClearAll={() => {}} onToggleDrawingsHidden={() => {}} onPositionSizeChange={() => {}} />);
  assert.ok(buttonTag(idle, 'data-drawing-tool="fib-extension"'), "the group shows its first variant before any choice");
});

test("a host can disable the calculated drawing group with its reason", () => {
  const html = renderInEnglish(<DrawingToolbar activeTool={null} penColor="#f59e0b" penSize={2}
    calculatedToolsUnavailableReason="Calculated drawings can't be saved in replay training yet"
    onClearAll={() => {}} onToggleDrawingsHidden={() => {}} onPositionSizeChange={() => {}} />);
  const button = buttonTag(html, 'data-drawing-tool="fib-extension"');
  assert.match(button, /disabled=""/);
  assert.ok(button.includes("can&#x27;t be saved in replay training yet") || button.includes("can't be saved in replay training yet"));
  assert.doesNotMatch(buttonTag(html, 'data-drawing-tool="line-segment"'), /disabled=""/);
});
