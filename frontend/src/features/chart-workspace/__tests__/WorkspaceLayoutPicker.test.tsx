import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

import { getLocale, setLocale } from "../../../i18n/index.js";
import {
  chartWorkspaceTemplateCellCount,
  createChartWorkspaceLayoutTree,
} from "../chartWorkspaceLayout.js";
import { CHART_WORKSPACE_TEMPLATE_IDS } from "../chartWorkspaceTypes.js";
import WorkspaceLayoutPicker, { LayoutThumbnail } from "../WorkspaceLayoutPicker.js";

function withLocale<T>(callback: () => T): T {
  const previous = getLocale();
  try {
    setLocale("en");
    return callback();
  } finally {
    setLocale(previous);
  }
}

test("layout thumbnails draw one cell per template slot", () => {
  for (const templateId of CHART_WORKSPACE_TEMPLATE_IDS) {
    const html = renderToStaticMarkup(<LayoutThumbnail tree={createChartWorkspaceLayoutTree(templateId)} />);
    assert.equal(html.match(/<rect /g)?.length, chartWorkspaceTemplateCellCount(templateId), templateId);
  }
});

test("layout trigger names the current layout and draws the live tree", () => {
  const html = withLocale(() => renderToStaticMarkup(
    <WorkspaceLayoutPicker
      tree={createChartWorkspaceLayoutTree("main-confirmation")}
      layout="main-confirmation"
      cellCount={3}
      maxCellsPerWindow={4}
      ready
      locked={false}
      saveState="saved"
      onSelectLayout={() => {}}
      onOpenManager={() => {}}
    />,
  ));
  assert.match(html, /aria-label="[^"]+: Main \/ confirm"/);
  assert.match(html, /aria-haspopup="dialog"/);
  assert.match(html, /aria-expanded="false"/);
  assert.equal(html.match(/<rect /g)?.length, 3);
  assert.doesNotMatch(html, /workspace-layout-popover/);
});

test("layout trigger carries the workspace save state for the error indicator", () => {
  const html = withLocale(() => renderToStaticMarkup(
    <WorkspaceLayoutPicker
      tree={createChartWorkspaceLayoutTree("single")}
      layout="custom"
      cellCount={2}
      maxCellsPerWindow={16}
      ready
      locked
      saveState="error"
      onSelectLayout={() => {}}
      onOpenManager={() => {}}
    />,
  ));
  assert.match(html, /data-save-state="error"/);
});
