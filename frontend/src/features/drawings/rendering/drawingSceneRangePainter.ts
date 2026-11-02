import type { DrawingDisplayEntity, DrawingScreenDisplayList } from "./drawingDisplayList.js";

/** Render projected measurements only; source-coordinate arithmetic stays outside paint. */
export function drawRangeSceneEntity(
  context: CanvasRenderingContext2D,
  entity: DrawingDisplayEntity,
  list: DrawingScreenDisplayList,
  horizontalPixelRatio: number,
  verticalPixelRatio: number,
): void {
  const spec = entity.renderSpec;
  if (spec?.op !== "range-measure" || entity.pointCount !== 4) return;
  const points = Array.from({ length: 4 }, (_, i) => ({
    x: Number(list.points[(entity.pointOffset + i) * 2]),
    y: Number(list.points[(entity.pointOffset + i) * 2 + 1]),
  }));
  const [a, b, labelA, labelB] = points;
  if (!a || !b || !labelA || !labelB || points.some((p) => !Number.isFinite(p.x) || !Number.isFinite(p.y))) return;
  context.save();
  context.scale(horizontalPixelRatio, verticalPixelRatio);
  context.strokeStyle = spec.strokeColor;
  context.fillStyle = spec.strokeColor;
  context.lineWidth = spec.lineWidthCssPx;
  const x = Math.min(a.x, b.x), y = Math.min(a.y, b.y);
  const width = Math.abs(b.x - a.x), height = Math.abs(b.y - a.y);
  context.globalAlpha = 0.08;
  context.fillRect(x, y, width, height);
  context.globalAlpha = 1;
  context.setLineDash([3, 3]);
  context.strokeRect(x, y, width, height);
  context.setLineDash([]);
  context.beginPath();
  if (spec.measureType !== "time") {
    context.moveTo(b.x, a.y); context.lineTo(b.x, b.y);
    context.moveTo(b.x - 4, a.y); context.lineTo(b.x + 4, a.y);
    context.moveTo(b.x - 4, b.y); context.lineTo(b.x + 4, b.y);
  }
  if (spec.measureType !== "price") {
    context.moveTo(a.x, a.y); context.lineTo(b.x, a.y);
    context.moveTo(a.x, a.y - 4); context.lineTo(a.x, a.y + 4);
    context.moveTo(b.x, a.y - 4); context.lineTo(b.x, a.y + 4);
  }
  context.stroke();
  context.fillStyle = "rgba(20, 24, 32, 0.94)";
  context.fillRect(labelA.x, labelA.y, labelB.x - labelA.x, labelB.y - labelA.y);
  context.fillStyle = "#ffffff";
  context.font = "11px sans-serif";
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillText(spec.labelText, (labelA.x + labelB.x) / 2, (labelA.y + labelB.y) / 2);
  if (spec.selected) {
    context.lineWidth = 2;
    for (const point of [a, b]) {
      context.beginPath(); context.arc(point.x, point.y, 5, 0, Math.PI * 2);
      context.fill(); context.stroke();
    }
  }
  context.restore();
}
