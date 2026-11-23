import { arrowHeadScreenGeometry } from "../geometry/drawingToolGeometry.js";
import type { DrawingDisplayEntity, DrawingScreenDisplayList } from "./drawingDisplayList.js";

export function drawPathSceneEntity(ctx: CanvasRenderingContext2D, entity: DrawingDisplayEntity,
  list: DrawingScreenDisplayList, ratioX: number, ratioY: number): void {
  const spec = entity.renderSpec;
  if (spec?.op !== "path" || entity.pointCount < 2) return;
  const point = (i: number) => ({ x: list.points[2 * i]!, y: list.points[2 * i + 1]! });
  const start = entity.pointOffset, last = start + entity.pointCount - 1, tip = point(last);
  let head = null;
  if (spec.arrowEnd) {
    for (let i = last - 1; i >= start && !head; i--) head = arrowHeadScreenGeometry(point(i), tip, spec.lineWidthCssPx);
  }
  ctx.save();
  ctx.scale(ratioX, ratioY);
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.strokeStyle = spec.strokeColor;
  ctx.lineWidth = spec.lineWidthCssPx;
  ctx.beginPath();
  ctx.moveTo(point(start).x, point(start).y);
  for (let i = start + 1; i <= last; i++) {
    const p = point(i);
    ctx.lineTo(p.x, p.y);
  }
  ctx.stroke();
  if (head) {
    ctx.fillStyle = spec.strokeColor;
    ctx.beginPath();
    ctx.moveTo(tip.x, tip.y);
    ctx.lineTo(head.left.x, head.left.y);
    ctx.lineTo(head.right.x, head.right.y);
    ctx.closePath();
    ctx.fill();
  }
  if (spec.selected) {
    ctx.fillStyle = "#fff";
    ctx.lineWidth = 2;
    for (let i = start; i <= last; i++) {
      const p = point(i);
      ctx.beginPath();
      ctx.arc(p.x, p.y, 5, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    }
  }
  ctx.restore();
}
