import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  Badge, Button, Checkbox, DateTimeInput, Disclosure, Field, FileDrop, IconButton, InlineAlert, Input, Section, SegmentedControl,
  Select, Stat, Switch, TabPanel, Tabs, buttonClassName, choiceKeyTarget, fromDateTimeInputValue, toDateTimeInputValue,
} from "../index.js";

test("buttons compose variant, size and width classes", () => {
  assert.equal(buttonClassName({}), "ui-btn");
  assert.equal(buttonClassName({ variant: "primary", size: "sm", fullWidth: true, className: "x" }), "ui-btn ui-btn-primary ui-btn-sm ui-btn-block x");
  const html = renderToStaticMarkup(<Button variant="danger" icon={<svg />}>Delete</Button>);
  assert.match(html, /^<button type="button" class="ui-btn ui-btn-danger">/);
  assert.match(html, /<span class="ui-btn-icon" aria-hidden="true">/);
});

test("icon buttons always have an accessible name and report toggle state", () => {
  const html = renderToStaticMarkup(<IconButton label="Close" icon={<svg />} pressed={false} />);
  assert.match(html, /aria-label="Close"/);
  assert.match(html, /title="Close"/);
  assert.match(html, /aria-pressed="false"/);
});

test("a field links its label, control and message", () => {
  const html = renderToStaticMarkup(<Field label="Price" hint="In USDT" required><Input /></Field>);
  const id = /<label class="ui-field-label" for="([^"]+)"/.exec(html)?.[1];
  assert.ok(id);
  assert.match(html, new RegExp(`<input class="ui-input" id="${id}" aria-describedby="${id}-message" required=""`));
  assert.match(html, new RegExp(`<p id="${id}-message" class="ui-field-hint">In USDT</p>`));

  const invalid = renderToStaticMarkup(<Field label="Price" hint="In USDT" error="Enter a number"><Select><option>a</option></Select></Field>);
  assert.match(invalid, /aria-invalid="true"/);
  assert.match(invalid, /class="ui-field-error">Enter a number</);
  assert.doesNotMatch(invalid, /In USDT/);
  assert.match(invalid, /class="ui-input ui-select"/);
});

test("an input outside a field keeps its own attributes", () => {
  assert.equal(renderToStaticMarkup(<Input size="sm" id="q" />), '<input class="ui-input ui-input-sm" id="q"/>');
});

test("checkbox and switch carry their description", () => {
  const box = renderToStaticMarkup(<Checkbox label="Sound" description="Play a tone" defaultChecked />);
  assert.match(box, /<input type="checkbox" class="ui-check-input" aria-describedby="[^"]+" checked=""/);
  const toggle = renderToStaticMarkup(<Switch checked label="Sync" onChange={() => undefined} />);
  assert.match(toggle, /role="switch" aria-checked="true"/);
});

test("arrow, Home and End keys move through enabled items and wrap", () => {
  const disabled = [false, true, false, false];
  assert.equal(choiceKeyTarget("ArrowRight", 0, disabled), 2);
  assert.equal(choiceKeyTarget("ArrowLeft", 0, disabled), 3);
  assert.equal(choiceKeyTarget("ArrowDown", 3, disabled), 0);
  assert.equal(choiceKeyTarget("Home", 3, [true, false, false]), 1);
  assert.equal(choiceKeyTarget("End", 0, [false, false, true]), 1);
  assert.equal(choiceKeyTarget("Enter", 0, disabled), null);
  assert.equal(choiceKeyTarget("ArrowRight", 0, []), null);
});

test("a segmented control is a radio group with one tab stop", () => {
  const html = renderToStaticMarkup(
    <SegmentedControl label="Theme" value="light" onChange={() => undefined}
      options={[{ value: "dark", label: "Dark" }, { value: "light", label: "Light" }, { value: "system", label: "System", disabled: true }]} />,
  );
  assert.match(html, /^<div role="radiogroup" aria-label="Theme" class="ui-segmented">/);
  assert.match(html, /role="radio" aria-checked="false" tabindex="-1"[^>]*>Dark</);
  assert.match(html, /role="radio" aria-checked="true" tabindex="0"[^>]*>Light</);
  assert.match(html, /disabled=""[^>]*>System</);
});

test("tabs and panels reference each other", () => {
  const tabs = renderToStaticMarkup(<Tabs id="t" label="Views" value="b" onChange={() => undefined} tabs={[{ value: "a", label: "A" }, { value: "b", label: "B", badge: 3 }]} />);
  assert.match(tabs, /role="tab" id="t-tab-b" aria-selected="true" aria-controls="t-panel-b" tabindex="0"/);
  assert.match(tabs, /<span class="ui-tab-badge">3<\/span>/);
  const panel = renderToStaticMarkup(<TabPanel tabsId="t" value="b">Body</TabPanel>);
  assert.match(panel, /role="tabpanel" id="t-panel-b" aria-labelledby="t-tab-b"/);
});

test("display primitives expose tone and structure", () => {
  assert.match(renderToStaticMarkup(<Badge tone="warning">Stale</Badge>), /data-tone="warning"/);
  assert.match(renderToStaticMarkup(<Stat label="P&amp;L" value="+12.4" tone="success" />), /<strong class="ui-stat-value">\+12\.4<\/strong>/);
  const section = renderToStaticMarkup(<Section title="Network" description="Proxy" level={2} actions={<Button>Test</Button>}>x</Section>);
  assert.match(section, /<h2 class="ui-section-title">Network<\/h2>/);
  assert.match(section, /class="ui-section-actions"/);
  assert.match(renderToStaticMarkup(<Disclosure summary="Technical details">x</Disclosure>), /^<details class="ui-disclosure"><summary class="ui-disclosure-summary">/);
  assert.match(renderToStaticMarkup(<InlineAlert tone="danger" title="Failed" />), /role="alert"/);
  assert.match(renderToStaticMarkup(<InlineAlert title="Saved" />), /role="status"/);
});

test("date-time values round-trip in UTC and reject impossible dates", () => {
  const epoch = Date.UTC(2026, 10, 12, 8, 5, 9);
  assert.equal(toDateTimeInputValue(epoch, true), "2026-11-12T08:05");
  assert.equal(toDateTimeInputValue(epoch, true, true), "2026-11-12T08:05:09");
  assert.equal(fromDateTimeInputValue("2026-11-12T08:05:09", true), epoch);
  assert.equal(fromDateTimeInputValue("2026-02-30T00:00", true), null);
  assert.equal(fromDateTimeInputValue("", true), null);
  assert.equal(toDateTimeInputValue(null, true), "");
  const local = fromDateTimeInputValue("2026-11-12T08:05", false);
  assert.equal(toDateTimeInputValue(local, false), "2026-11-12T08:05");
});

test("the date-time input always shows its zone", () => {
  const html = renderToStaticMarkup(<DateTimeInput value={Date.UTC(2026, 0, 2, 3, 4)} onChange={() => undefined} />);
  assert.match(html, /type="datetime-local"/);
  assert.match(html, /value="2026-01-02T03:04"/);
  assert.match(html, /<span class="ui-datetime-zone">UTC<\/span>/);
});

test("the file drop is a labelled file input", () => {
  const html = renderToStaticMarkup(<FileDrop label="Drop a CSV file" hint="Up to 50 MB" accept=".csv" onFiles={() => undefined} />);
  const id = /<label for="([^"]+)" class="ui-file-drop"/.exec(html)?.[1];
  assert.ok(id);
  assert.match(html, new RegExp(`<input id="${id}" type="file" class="ui-file-drop-input" accept=".csv"`));
});
