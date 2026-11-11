import type { DrawingDisplayEntity, DrawingScreenDisplayList } from "./drawingDisplayList.js";

function pointAt(list: DrawingScreenDisplayList, index: number): { x: number; y: number } | null {
  const x = Number(list.points[index * 2]);
  const y = Number(list.points[index * 2 + 1]);
  return Number.isFinite(x) && Number.isFinite(y) ? { x, y } : null;
}

/** Paint a projected parallel channel; all geometry was resolved by the projector. */
export function drawChannelSceneEntity(
  context: CanvasRenderingContext2D,
  entity: DrawingDisplayEntity,
  list: DrawingScreenDisplayList,
  horizontalPixelRatio: number,
  verticalPixelRatio: number,
): void {
  const spec = entity.renderSpec;
  if (spec?.op !== "channel" || entity.pointCount !== 7) return;
  const base = entity.pointOffset;
  const start = pointAt(list, base + spec.polygonPointOffset);
  const end = pointAt(list, base + spec.polygonPointOffset + 1);
  const parallelEnd = pointAt(list, base + spec.polygonPointOffset + 2);
  const parallelStart = pointAt(list, base + spec.polygonPointOffset + 3);
  const midStart = pointAt(list, base + spec.midlinePointOffset);
  const midEnd = pointAt(list, base + spec.midlinePointOffset + 1);
  const offsetHandle = pointAt(list, base + spec.offsetHandlePointOffset);
  if (!start || !end || !parallelEnd || !parallelStart || !midStart || !midEnd || !offsetHandle) return;

  context.save();
  context.scale(horizontalPixelRatio, verticalPixelRatio);
  context.lineCap = "round";
  context.lineJoin = "round";
  if (spec.fillPaintColor) {
    context.fillStyle = spec.fillPaintColor;
    context.beginPath();
    context.moveTo(start.x, start.y);
    context.lineTo(end.x, end.y);
    context.lineTo(parallelEnd.x, parallelEnd.y);
    context.lineTo(parallelStart.x, parallelStart.y);
    context.closePath();
    context.fill();
  }
  context.strokeStyle = spec.strokeColor;
  context.lineWidth = spec.lineWidthCssPx;
  context.beginPath();
  context.moveTo(start.x, start.y);
  context.lineTo(end.x, end.y);
  context.moveTo(parallelStart.x, parallelStart.y);
  context.lineTo(parallelEnd.x, parallelEnd.y);
  context.stroke();

  context.globalAlpha = 0.7;
  context.lineWidth = Math.max(1, spec.lineWidthCssPx / 2);
  context.setLineDash([6, 4]);
  context.beginPath();
  context.moveTo(midStart.x, midStart.y);
  context.lineTo(midEnd.x, midEnd.y);
  context.stroke();
  context.setLineDash([]);
  context.globalAlpha = 1;

  if (spec.selected) {
    context.fillStyle = "#ffffff";
    context.lineWidth = 2;
    context.shadowColor = "rgba(0,0,0,0.3)";
    context.shadowBlur = 4;
    for (const handle of [start, end, offsetHandle]) {
      context.beginPath();
      context.arc(handle.x, handle.y, 5, 0, Math.PI * 2);
      context.fill();
      context.stroke();
    }
    context.shadowBlur = 0;
  }
  context.restore();
}
