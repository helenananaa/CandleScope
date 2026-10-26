import assert from "node:assert/strict";
import test from "node:test";
import { replayDisplayIntervalOptions, replayWorkspaceSelectionCommand } from "../replayWorkspaceSelection.js";

test("custom display intervals require an authoritative command before stepping", () => {
  const command = replayWorkspaceSelectionCommand({ selected_track_id: "sol", display_interval: "1m" }, "sol", "7m");
  assert.equal(command?.type, "set_display_interval");
  assert.equal(command?.value, "7m");
  assert.equal(replayWorkspaceSelectionCommand({ selected_track_id: "sol", display_interval: "7m" }, "sol", "7m"), null);
});

test("changing market selects its adapter before synchronizing the new chart interval", () => {
  const old = { selected_track_id: "ltc", display_interval: "5m" };
  assert.equal(replayWorkspaceSelectionCommand(old, "sol", "1w")?.type, "select_track");
  const selected = { ...old, selected_track_id: "sol" };
  assert.equal(replayWorkspaceSelectionCommand(selected, "sol", "1w")?.value, "1w");
});

test("late completion reconciles to the latest active chart without resubmitting the old target", () => {
  const pending = replayWorkspaceSelectionCommand({ selected_track_id: "sol", display_interval: "1m" }, "sol", "7m")!;
  const after = replayWorkspaceSelectionCommand({ selected_track_id: "sol", display_interval: "7m" }, "sol", "90m")!;
  assert.notEqual(after.key, pending.key);
  assert.equal(after.value, "90m");
});

test("equivalent hour labels do not cause a command loop but month and minute stay distinct", () => {
  assert.equal(replayWorkspaceSelectionCommand({ selected_track_id: "sol", display_interval: "60m" }, "sol", "1h"), null);
  assert.equal(replayWorkspaceSelectionCommand({ selected_track_id: "sol", display_interval: "1m" }, "sol", "1M")?.value, "1M");
});

test("unavailable authority or market cannot produce a speculative command", () => {
  assert.equal(replayWorkspaceSelectionCommand(null, "sol", "7m"), null);
  assert.equal(replayWorkspaceSelectionCommand({ selected_track_id: "sol", display_interval: "1m" }, undefined, "7m"), null);
  assert.equal(replayWorkspaceSelectionCommand({ selected_track_id: null, display_interval: "1m" }, "sol", "7m")?.type, "select_track");
});

test("stepping choices include current custom and calendar intervals and respect source divisibility", () => {
  const minute = replayDisplayIntervalOptions("1m", "7m");
  for (const interval of ["1m", "7m", "1w", "1M", "12M"]) assert.ok(minute.includes(interval));
  assert.equal(minute.filter((interval) => interval === "1m").length, 1);
  const five = replayDisplayIntervalOptions("5m", "90m");
  assert.ok(five.includes("90m"));
  assert.ok(!five.includes("1m") && !five.includes("3m"));
  assert.ok(!replayDisplayIntervalOptions("5m", "7m").includes("7m"));
});
