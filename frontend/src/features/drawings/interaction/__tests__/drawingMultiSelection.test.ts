import assert from "node:assert/strict";
import test from "node:test";

import { applyDrawingCommands } from "../../core/drawingCommands.js";
import { exportDrawingDocument } from "../../core/drawingCodec.js";
import { createDrawingDocument, type DrawingDocument } from "../../core/drawingDocument.js";
import { createDrawingDocumentStore } from "../../core/drawingDocumentStore.js";
import { isDrawingGroupId, nextDrawingGroupId } from "../../drawingGroups.js";
import { normalizeSavedDrawingItem, normalizeSavedDrawingItemStrict } from "../../drawingPersistence.js";
import type { DrawingDataPoint, SavedDrawing, ScreenPoint } from "../../drawingTypes.js";
import { clearDrawingClipboard, copyDrawingSelection, pastedDrawings, readDrawingClipboard } from "../drawingClipboard.js";
import {
  createAxisLineSavedDrawing,
  createPositionSavedDrawing,
  createTextSavedDrawing,
  createTwoPointSavedDrawing,
  drawingCreateCommandsForSavedDrawing,
} from "../drawingEntityCreation.js";
import { groupMoveDescriptor, groupMoveDrafts, snappedGroupDelta, type GroupMoveContext } from "../drawingGroupMove.js";
import {
  deleteSelectionCommands,
  drawingSelection,
  EMPTY_DRAWING_SELECTION,
  groupMemberIds,
  groupSelectionCommands,
  selectAllDrawings,
  selectionAfterClick,
  selectionIsGrouped,
  ungroupSelectionCommands,
} from "../drawingMultiSelection.js";

const T0 = 1_700_000_000;
const BAR = 300;
const point = (minutes: number, price: number): DrawingDataPoint => ({ time: T0 + minutes * 60, price });

/** One screen pixel is one minute and one price unit; snapping rounds to 5-minute bars and whole prices. */
const context: GroupMoveContext = {
  dataToScreen: (data) => (typeof data.time === "number" ? { x: (data.time - T0) / 60, y: 1000 - data.price } : null),
  screenToData: (x, y) => ({ time: T0 + x * 60, price: 1000 - y }),
  screenToDrawingData: (x, y, options = {}) => {
    const time = T0 + x * 60;
    const price = 1000 - y;
    return options.snap ? { time: Math.round((time - T0) / BAR) * BAR + T0, price: Math.round(price) } : { time, price };
  },
};

function line(a: DrawingDataPoint, b: DrawingDataPoint): SavedDrawing {
  const created = createTwoPointSavedDrawing({ tool: "line-segment", color: "#3b82f6", lineWidth: 2, dataPoints: [a, b] });
  assert.ok(created);
  return created;
}

function documentWith(drawings: readonly SavedDrawing[], scopeKey = "binance:BTCUSDT:spot"): DrawingDocument {
  const commands = drawings.flatMap((drawing) => drawingCreateCommandsForSavedDrawing(drawing) ?? []);
  const result = applyDrawingCommands(createDrawingDocument({ scopeKey }), commands);
  assert.equal(result.ok, true);
  return result.document;
}

/** Dispatches one batch through a store and undoes it once: the batch must be one history step. */
function assertOneUndoStep(document: DrawingDocument, commands: readonly unknown[] | null): DrawingDocument {
  assert.ok(commands);
  const store = createDrawingDocumentStore(document);
  assert.equal(store.dispatchMany(commands as never).ok, true);
  const after = store.getSnapshot();
  assert.equal(store.replayHistory("undo", (inverse) => store.dispatchMany(inverse).ok), true);
  assert.deepEqual(store.getSnapshot().zOrder, document.zOrder);
  assert.deepEqual(exportDrawingDocument(store.getSnapshot()), exportDrawingDocument(document));
  assert.equal(store.canUndo, false, "one undo restores the whole batch");
  return after;
}

function apply(document: DrawingDocument, commands: readonly unknown[] | null): DrawingDocument {
  assert.ok(commands);
  const result = applyDrawingCommands(document, commands as never);
  assert.equal(result.ok, true, result.ok ? "" : String(result.error));
  return result.document;
}

test("group ids are strict and new ones are unique", () => {
  const first = nextDrawingGroupId(1);
  const second = nextDrawingGroupId(1);
  assert.equal(isDrawingGroupId(first), true);
  assert.notEqual(first, second);
  for (const bad of ["", "grp_", "group_1", "grp_a b", `grp_${"x".repeat(65)}`, 7, null]) assert.equal(isDrawingGroupId(bad), false);
});

test("a plain click selects the drawing with its group; shift toggles it", () => {
  const [a, b, c] = [line(point(0, 100), point(10, 110)), line(point(20, 100), point(30, 120)), line(point(40, 90), point(50, 95))];
  let document = documentWith([a!, b!, c!]);
  assert.deepEqual(selectionAfterClick(document, EMPTY_DRAWING_SELECTION, a!.id!, false).ids, [a!.id]);

  let selection = selectionAfterClick(document, EMPTY_DRAWING_SELECTION, a!.id!, false);
  selection = selectionAfterClick(document, selection, c!.id!, true);
  assert.deepEqual(selection.ids, [a!.id, c!.id]);
  assert.equal(selection.primary, c!.id);
  // A plain click on a selected member keeps the set so it can be dragged.
  assert.deepEqual(selectionAfterClick(document, selection, a!.id!, false).ids, [a!.id, c!.id]);
  selection = selectionAfterClick(document, selection, c!.id!, true);
  assert.deepEqual(selection.ids, [a!.id]);

  document = apply(document, groupSelectionCommands(document, drawingSelection(document, a!.id!, [a!.id!, b!.id!]), "grp_test"));
  assert.deepEqual(groupMemberIds(document, b!.id!), [a!.id, b!.id]);
  assert.deepEqual(selectionAfterClick(document, EMPTY_DRAWING_SELECTION, b!.id!, false).ids, [a!.id, b!.id]);
  // Shift on a grouped drawing adds or removes the whole group.
  const withGroup = selectionAfterClick(document, drawingSelection(document, c!.id!, [c!.id!]), a!.id!, true);
  assert.deepEqual(withGroup.ids, [a!.id, b!.id, c!.id]);
  assert.deepEqual(selectionAfterClick(document, withGroup, b!.id!, true).ids, [c!.id]);
});

test("select all keeps only drawings visible on the interval, in z-order", () => {
  const visible = line(point(0, 100), point(10, 110));
  const hidden = { ...line(point(0, 120), point(10, 130)), hidden: true } as SavedDrawing;
  const otherInterval = { ...line(point(0, 140), point(10, 150)), visibleIntervals: ["1d"] } as SavedDrawing;
  const document = documentWith([visible, hidden, otherInterval]);
  assert.deepEqual(selectAllDrawings(document, "1h").ids, [visible.id]);
  assert.deepEqual(selectAllDrawings(document, "1d").ids, [visible.id, otherInterval.id]);
});

test("grouping and ungrouping are single batches that survive the codec and strict persistence", () => {
  const [a, b] = [line(point(0, 100), point(10, 110)), line(point(20, 100), point(30, 120))];
  let document = documentWith([a!, b!]);
  const selection = drawingSelection(document, b!.id!, [a!.id!, b!.id!]);
  assert.equal(groupSelectionCommands(document, drawingSelection(document, a!.id!, [a!.id!])), null, "one drawing is not a group");
  const commands = groupSelectionCommands(document, selection, "grp_pair");
  assert.equal(commands?.length, 2);
  assertOneUndoStep(document, commands);
  document = apply(document, commands);
  assert.equal(selectionIsGrouped(document, selection), true);
  const exported = exportDrawingDocument(document);
  assert.ok(exported);
  assert.deepEqual(exported.map((drawing) => drawing.groupId), ["grp_pair", "grp_pair"]);
  for (const drawing of exported) {
    assert.equal(normalizeSavedDrawingItemStrict(drawing)?.groupId, "grp_pair");
    assert.equal(normalizeSavedDrawingItem(drawing)?.groupId, "grp_pair");
  }
  assert.equal(normalizeSavedDrawingItemStrict({ ...exported[0]!, groupId: "not a group" }), null);

  document = apply(document, ungroupSelectionCommands(document, selection));
  assert.deepEqual(exportDrawingDocument(document)?.map((drawing) => drawing.groupId), [undefined, undefined]);
  assert.equal(ungroupSelectionCommands(document, selection), null);
});

test("deleting a multi-selection is one batch", () => {
  const drawings = [line(point(0, 100), point(10, 110)), line(point(20, 100), point(30, 120)), line(point(40, 90), point(50, 95))];
  let document = documentWith(drawings);
  const commands = deleteSelectionCommands(document, drawingSelection(document, null, [drawings[0]!.id!, drawings[2]!.id!]));
  assertOneUndoStep(document, commands);
  document = apply(document, commands);
  assert.deepEqual(document.zOrder, [drawings[1]!.id]);
});

test("copy and paste make new drawings with new ids and new groups, unlocked", () => {
  clearDrawingClipboard();
  const [a, b] = [line(point(0, 100), point(10, 110)), line(point(20, 100), point(30, 120))];
  let document = documentWith([a!, { ...b!, locked: true } as SavedDrawing]);
  document = apply(document, groupSelectionCommands(document, drawingSelection(document, a!.id!, [a!.id!, b!.id!]), "grp_source"));
  assert.equal(copyDrawingSelection(document, drawingSelection(document, a!.id!, [a!.id!, b!.id!])), 2);
  const clipboard = readDrawingClipboard();
  assert.equal(clipboard?.sourceScope, "binance:BTCUSDT:spot");

  const pasted = pastedDrawings(clipboard!, (drawing) => drawing);
  assert.equal(pasted?.length, 2);
  const ids = pasted!.map((drawing) => drawing.id);
  assert.equal(new Set(ids).size, 2);
  for (const id of ids) assert.ok(id && id !== a!.id && id !== b!.id && id.startsWith("ln_"));
  const groups = new Set(pasted!.map((drawing) => drawing.groupId));
  assert.equal(groups.size, 1);
  assert.notEqual([...groups][0], "grp_source");
  assert.equal(pasted!.some((drawing) => drawing.locked), false);

  // The copies can be created next to the originals in one batch.
  const creates = pasted!.flatMap((drawing) => drawingCreateCommandsForSavedDrawing(drawing) ?? []);
  document = apply(document, creates);
  assert.equal(document.zOrder.length, 4);
  // A paste whose placement fails creates nothing.
  assert.equal(pastedDrawings(clipboard!, () => null), null);
  clearDrawingClipboard();
  assert.equal(readDrawingClipboard(), null);
});

test("a group moves by one delta and keeps its shape across drawing kinds", () => {
  const segment = line(point(0, 100), point(10, 110));
  const text = createTextSavedDrawing({ dataPoint: point(20, 130), text: "Note", color: "#fff", fontSize: 14 } as never);
  const horizontal = createAxisLineSavedDrawing({ tool: "line-horizontal", dataPoint: point(5, 90), color: "#f00", lineWidth: 1 });
  const position = createPositionSavedDrawing({ tool: "position-long", dataPoint: point(30, 100), timeRange: { start: T0 + 30 * 60, end: T0 + 60 * 60 } } as never);
  const members = [segment, text, horizontal, position].map((original) => {
    assert.ok(original);
    const descriptor = groupMoveDescriptor(original, { x: 0, y: 0 }, context);
    assert.ok(descriptor, `${original.type} can move with a group`);
    return { original, descriptor };
  });
  const drafts = groupMoveDrafts(members, { dx: 15, dy: -10 }, context);
  assert.ok(drafts);
  const [movedLine, movedText, movedAxis, movedPosition] = drafts as [SavedDrawing, SavedDrawing, SavedDrawing, SavedDrawing];
  assert.deepEqual("dataPoints" in movedLine ? movedLine.dataPoints : null, [point(15, 110), point(25, 120)]);
  assert.deepEqual(movedText.type === "text" ? movedText.dataPoint : null, point(35, 140));
  assert.equal(movedAxis.type === "axis-line" ? movedAxis.dataPoint?.price : null, 100);
  assert.equal(movedPosition.type === "position" ? movedPosition.entryPrice : null, 110);

  // A locked member makes the whole selection immovable.
  assert.equal(groupMoveDescriptor({ ...segment, locked: true } as SavedDrawing, { x: 0, y: 0 }, context), null);
});

test("group snapping corrects the delta by the primary's first anchor only", () => {
  const primary = line(point(1, 100.4), point(11, 110));
  const other = line(point(3, 50.2), point(7, 60));
  // Raw move of 3 px right lands the primary's first anchor at minute 4, which snaps to minute 5 and price 100.
  const delta = snappedGroupDelta(primary, { dx: 3, dy: 0 }, context, true);
  assert.equal(delta.dx, 4);
  assert.ok(Math.abs(delta.dy - 0.4) < 1e-9);
  assert.deepEqual(snappedGroupDelta(primary, { dx: 3, dy: 0 }, context, false), { dx: 3, dy: 0 });
  const members = [primary, other].map((original) => ({ original, descriptor: groupMoveDescriptor(original, { x: 0, y: 0 } as ScreenPoint, context)! }));
  const [movedPrimary, movedOther] = groupMoveDrafts(members, delta, context)!;
  const first = (drawing: SavedDrawing | undefined) => (drawing && "dataPoints" in drawing ? drawing.dataPoints[0] : null);
  assert.equal(first(movedPrimary)?.time, T0 + 5 * 60);
  assert.ok(Math.abs((first(movedPrimary)?.price ?? 0) - 100) < 1e-9);
  // The other member moves by the same corrected delta, not to its own snap target.
  assert.equal(first(movedOther)?.time, T0 + 7 * 60);
  assert.ok(Math.abs((first(movedOther)?.price ?? 0) - 49.8) < 1e-9);
});
