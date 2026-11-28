import type { DrawingDisplayEntity, DrawingScreenDisplayList } from "./drawingDisplayList.js";

function pointAt(list: DrawingScreenDisplayList, index: number): { x: number; y: number } | null {
  const x = Number(list.points[index * 2]);
  const y = Number(list.points[index * 2 + 1]);
  return Number.isFinite(x) && Number.isFinite(y) ? { x, y } : null;
}

/**
 * Paint a projected calculated drawing in CSS pixels. Every value was resolved
 * by the projector; non-finite points break a line instead of being bridged.
 */
export function drawCalculatedSceneEntity(
  context: CanvasRenderingContext2D,
  entity: DrawingDisplayEntity,
  list: DrawingScreenDisplayList,
  horizontalPixelRatio: number,
  verticalPixelRatio: number,
): void {
  const spec = entity.renderSpec;
  if (spec?.op !== "calculated") return;
  const base = entity.pointOffset;
  context.save();
  context.scale(horizontalPixelRatio, verticalPixelRatio);
  context.lineCap = "round";
  context.lineJoin = "round";

  for (const polygon of spec.polygons) {
    context.fillStyle = polygon.fillColor;
    context.beginPath();
    let started = false;
    for (let index = 0; index < polygon.pointCount; index += 1) {
      const point = pointAt(list, base + polygon.pointOffset + index);
      if (!point) { started = false; break; }
      if (started) context.lineTo(point.x, point.y);
      else context.moveTo(point.x, point.y);
      started = true;
    }
    if (started) {
      context.closePath();
      context.fill();
    }
  }

  for (const box of spec.boxes) {
    const first = pointAt(list, base + box.pointOffset);
    const second = pointAt(list, base + box.pointOffset + 1);
    if (!first || !second) continue;
    context.fillStyle = box.fillColor;
    context.fillRect(
      Math.min(first.x, second.x),
      Math.min(first.y, second.y),
      Math.abs(second.x - first.x),
      Math.abs(second.y - first.y),
    );
  }

  for (const line of spec.lines) {
    context.strokeStyle = line.color;
    context.lineWidth = line.widthCssPx;
    context.setLineDash(line.dashed ? [6, 4] : []);
    context.beginPath();
    let pen = false;
    for (let index = 0; index < line.pointCount; index += 1) {
      const point = pointAt(list, base + line.pointOffset + index);
      if (!point) {
        pen = false;
        continue;
      }
      if (pen) context.lineTo(point.x, point.y);
      else context.moveTo(point.x, point.y);
      pen = true;
    }
    context.stroke();
  }
  context.setLineDash([]);

  if (spec.labels.length > 0) {
    context.font = "11px sans-serif";
    context.textBaseline = "bottom";
    for (const label of spec.labels) {
      const point = pointAt(list, base + label.pointOffset);
      if (!point) continue;
      context.fillStyle = label.color;
      context.textAlign = label.align === "right" ? "right" : "left";
      context.fillText(label.text, point.x + (label.align === "right" ? -6 : 6), point.y - 2);
    }
  }

  if (spec.selected && spec.handleCount > 0) {
    context.fillStyle = "#ffffff";
    context.strokeStyle = spec.strokeColor;
    context.lineWidth = 2;
    context.shadowColor = "rgba(0,0,0,0.3)";
    context.shadowBlur = 4;
    for (let index = 0; index < spec.handleCount; index += 1) {
      const handle = pointAt(list, base + spec.handlePointOffset + index);
      if (!handle) continue;
      context.beginPath();
      context.arc(handle.x, handle.y, 5, 0, Math.PI * 2);
      context.fill();
      context.stroke();
    }
    context.shadowBlur = 0;
  }
  context.restore();
}
