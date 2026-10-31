import type { IPrimitivePaneRenderer, IPrimitivePaneView, SeriesAttachedParameter, SeriesType } from "lightweight-charts";
import type { ChartTime } from "./chartAdapterTypes.js";
import { prepareDrawingCoordinateContext, resolveDrawingDataPointsToCoordinates } from "./coordinateBridge.js";
import { drawingColor as color, drawingNumber as num, drawingRows as rows, drawingText as text, drawingCellSpan } from "../features/backtest/native/nativeDrawingModel.js";

type Row = Record<string, unknown>;
type Point = { x: number; y: number };
type Attached = SeriesAttachedParameter<ChartTime, SeriesType>;
const array = (value: unknown): unknown[] => Array.isArray(value) ? value : [];
const record = (value: unknown): Row => value !== null && typeof value === "object" && !Array.isArray(value) ? value as Row : {};
const fontSize = (v: unknown) => Math.max(8, Math.min(36, num(v) ?? ({ tiny: 9, small: 11, normal: 14, large: 18, huge: 24 }[text(v).split(".").at(-1)!] ?? 12)));
const dash = (v: unknown) => text(v).includes("dotted") ? [2, 4] : text(v).includes("dashed") ? [8, 5] : [];

export function pineSceneRange(scene: Row) {
  const values: number[] = [];
  const include = (v: unknown) => { const n = num(v); if (n !== undefined) values.push(n); };
  for (const object of rows(scene.objects)) {
    const row = record(object.row);
    for (const k of ["y", "y1", "y2", "top", "bottom"]) include(row[k]);
    rows(row.points).forEach((p) => include(p.price ?? p.y));
  }
  const plots = record(scene.plots);
  if (rows(plots.plotChars).length || rows(plots.plotArrows).length) {
    array(scene.highs).forEach(include); array(scene.lows).forEach(include);
  }
  for (const kind of ["plotBars", "plotCandles"]) for (const row of rows(plots[kind])) {
    array(row.highs).forEach(include); array(row.lows).forEach(include);
  }
  if (!values.length) return null;
  let minValue = Infinity, maxValue = -Infinity;
  values.forEach((v) => { minValue = Math.min(minValue, v); maxValue = Math.max(maxValue, v); });
  return { priceRange: { minValue, maxValue } };
}

/** A pane-owned primitive: every object is projected against the chart's actual scales. */
export class PineScenePrimitive {
  private attachment: Attached | null = null;
  private scene: Row = {};
  private readonly view: IPrimitivePaneView;
  constructor(scene: Row) {
    this.scene = scene;
    this.view = { zOrder: () => "normal", renderer: () => ({ draw: (target) => this.draw(target) }) };
  }
  attached(attachment: Attached) { this.attachment = attachment; attachment.requestUpdate(); }
  detached() { this.attachment = null; }
  setScene(scene: Row) { this.scene = scene; this.attachment?.requestUpdate(); }
  updateAllViews() { /* Projection happens at paint time, including zoom and scale changes. */ }
  paneViews() { return [this.view]; }
  autoscaleInfo() { return pineSceneRange(this.scene); }

  private draw(target: Parameters<IPrimitivePaneRenderer["draw"]>[0]) {
    const attached = this.attachment, scene = this.scene;
    if (!attached || scene.schemaVersion !== 1) return;
    const times = array(scene.times).map(Number);
    if (!times.length || times.length > 100000) return;
    const context = prepareDrawingCoordinateContext(attached.series);
    const timeAt = (index: number) => {
      const left = Math.max(0, Math.min(times.length - 2, Math.floor(index)));
      return times[left]! + (index - left) * ((times[left + 1] ?? times[left]! + 60) - times[left]!);
    };
    const x = (time: number) => resolveDrawingDataPointsToCoordinates(attached.chart, attached.series, [{ time: time as ChartTime }], context)[0] ?? null;
    const y = (value: unknown) => num(value) === undefined ? null : attached.series.priceToCoordinate(Number(value));
    const point = (row: Row, xv: unknown, yv: unknown): Point | null => {
      if (num(xv) === undefined) return null;
      const px = x(text(row.xloc).endsWith("bar_time") ? Number(xv) / 1000 : timeAt(Number(xv))), py = y(yv);
      return px === null || py === null ? null : { x: px, y: py };
    };
    target.useBitmapCoordinateSpace((scope) => {
      const c = scope.context, width = scope.bitmapSize.width / scope.horizontalPixelRatio, height = scope.bitmapSize.height / scope.verticalPixelRatio;
      c.save();
      c.scale(scope.horizontalPixelRatio, scope.verticalPixelRatio);
      c.beginPath(); c.rect(0, 0, width, height); c.clip();
      const path = (points: Point[], closed = false, curved = false) => {
        c.beginPath(); if (!points.length) return;
        c.moveTo(points[0]!.x, points[0]!.y);
        const p = closed ? [...points, points[0]!] : points;
        for (let i = 1; i < p.length; i++) {
          if (curved) {
            const a = p[Math.max(0, i - 2)]!, b = p[i - 1]!, d = p[i]!, e = p[Math.min(p.length - 1, i + 1)]!;
            c.bezierCurveTo(b.x + (d.x - a.x) / 6, b.y + (d.y - a.y) / 6, d.x - (e.x - b.x) / 6, d.y - (e.y - b.y) / 6, d.x, d.y);
          } else c.lineTo(p[i]!.x, p[i]!.y);
        }
        if (closed) c.closePath();
      };
      const stroke = (points: Point[], row: Row, closed = false, curved = false) => {
        path(points, closed, curved); c.strokeStyle = color(row.color ?? row.linecolor);
        c.lineWidth = Math.min(32, Math.max(1, num(row.width ?? row.linewidth) ?? 1));
        c.setLineDash(dash(row.style ?? row.linestyle)); c.stroke(); c.setLineDash([]);
      };
      const objects = rows(scene.objects).slice(0, 5000);
      const lines = new Map<string, Point[]>();
      for (const object of objects) if (object.kind === "lines") {
        const row = record(object.row), a = point(row, row.x1, row.y1), b = point(row, row.x2, row.y2);
        if (!a || !b) continue;
        const lo = a.x <= b.x ? a : b, hi = a.x <= b.x ? b : a, ext = text(row.extend);
        const slope = hi.x === lo.x ? 0 : (hi.y - lo.y) / (hi.x - lo.x);
        lines.set(text(row.id), [ext.endsWith("left") || ext.endsWith("both") ? { x: 0, y: lo.y - slope * lo.x } : lo,
          ext.endsWith("right") || ext.endsWith("both") ? { x: width, y: hi.y + slope * (width - hi.x) } : hi]);
      }
      for (const object of objects) {
        const row = record(object.row), kind = text(object.kind);
        if (kind === "lines") { const p = lines.get(text(row.id)); if (p) stroke(p, row); }
        else if (kind === "linefills") {
          const a = lines.get(text(row.line1 ?? row.line1id)), b = lines.get(text(row.line2 ?? row.line2id));
          if (a && b) { path([...a, ...[...b].reverse()], true); c.fillStyle = color(row.color, "transparent"); c.fill(); }
        } else if (kind === "polylines") {
          const points = rows(row.points).map((p) => point(row, text(row.xloc).endsWith("bar_time") ? p.time : p.index, p.price)).filter((p): p is Point => p !== null);
          if (row.closed) { path(points, true, row.curved === true); c.fillStyle = color(row.fillcolor, "transparent"); c.fill(); }
          stroke(points, row, row.closed === true, row.curved === true);
        } else if (kind === "boxes") {
          const a = point(row, row.left, row.top), b = point(row, row.right, row.bottom); if (!a || !b) continue;
          const ext = text(row.extend), left = ext.endsWith("left") || ext.endsWith("both") ? 0 : Math.min(a.x, b.x);
          const right = ext.endsWith("right") || ext.endsWith("both") ? width : Math.max(a.x, b.x), top = Math.min(a.y, b.y), bottom = Math.max(a.y, b.y);
          c.fillStyle = color(row.bgcolor, "transparent"); c.fillRect(left, top, right - left, bottom - top);
          stroke([{ x: left, y: top }, { x: right, y: top }, { x: right, y: bottom }, { x: left, y: bottom }], { color: row.bordercolor, width: row.borderwidth, style: row.borderstyle }, true);
          c.font = `${fontSize(row.textsize)}px sans-serif`; c.textAlign = "center"; c.fillStyle = color(row.textcolor); c.fillText(text(row.text), (left + right) / 2, (top + bottom) / 2);
        } else if (kind === "labels") {
          let price = row.y;
          const index = text(row.xloc).endsWith("bar_time") ? times.indexOf(Number(row.x) / 1000) : Number(row.x);
          if (text(row.yloc).endsWith("abovebar")) price = array(scene.highs)[index];
          if (text(row.yloc).endsWith("belowbar")) price = array(scene.lows)[index];
          const p = point(row, row.x, price); if (!p) continue;
          const size = fontSize(row.size), label = text(row.text), offset = text(row.yloc).endsWith("belowbar") ? size : -5;
          c.font = `${size}px sans-serif`; c.textAlign = "center";
          c.fillStyle = color(row.color, "transparent"); c.fillRect(p.x - c.measureText(label).width / 2 - 3, p.y + offset - size, c.measureText(label).width + 6, size + 4);
          c.fillStyle = color(row.textcolor, "#e2e8f0"); c.fillText(label, p.x, p.y + offset);
        } else if (kind === "tables") {
          const columns = num(row.columns) ?? 0, count = num(row.rows) ?? 0;
          if (!Number.isInteger(columns) || !Number.isInteger(count) || columns <= 0 || count <= 0 || columns * count > 10000) continue;
          const cells = rows(row.cells), position = text(row.position), cw = Math.min(140, Math.max(50, ...cells.map((cell) => text(cell.text).length * 7 + 10))), ch = 24;
          const left = position.includes("right") ? width - columns * cw - 6 : position.includes("center") ? (width - columns * cw) / 2 : 6;
          const top = position.includes("bottom") ? height - count * ch - 6 : position.includes("middle") ? (height - count * ch) / 2 : 6;
          c.fillStyle = color(row.bgcolor, "transparent"); c.fillRect(left, top, columns * cw, count * ch);
          for (const cell of cells) {
            const r = Number(cell.row), col = Number(cell.column), span = drawingCellSpan(r, col, rows(row.mergedcells)); if (span.hidden) continue;
            const px = left + col * cw, py = top + r * ch;
            c.fillStyle = color(cell.bgcolor, "transparent"); c.fillRect(px, py, cw * span.colSpan, ch * span.rowSpan);
            c.font = `${fontSize(cell.textsize)}px sans-serif`; c.textAlign = "center"; c.fillStyle = color(cell.textcolor, "#e2e8f0");
            c.fillText(text(cell.text), px + cw * span.colSpan / 2, py + ch * span.rowSpan / 2 + 4, cw * span.colSpan - 6);
          }
          c.strokeStyle = color(row.framecolor, "transparent"); c.lineWidth = num(row.framewidth) ?? 1; c.strokeRect(left, top, columns * cw, count * ch);
        }
      }
      const plots = record(scene.plots), at = (row: Row, key: string, i: number) => array(row[key])[i];
      const barWidth = Math.max(1, Math.min(24, Math.abs((x(timeAt(1)) ?? 8) - (x(timeAt(0)) ?? 0)) * .7));
      for (const [kind, items] of Object.entries(plots)) for (const row of rows(items)) {
        for (let i = Math.max(0, times.length - (num(row.showLast) ?? times.length)); i < times.length; i++) {
          const px = x(timeAt(i + (num(row.offset) ?? 0))); if (px === null || px < -30 || px > width + 30) continue;
          if (kind === "plotCandles" || kind === "plotBars") {
            const o = y(at(row, "opens", i)), h = y(at(row, "highs", i)), l = y(at(row, "lows", i)), cl = y(at(row, "closes", i));
            if (o === null || h === null || l === null || cl === null) continue;
            stroke([{ x: px, y: h }, { x: px, y: l }], { color: at(row, "wickColors", i) ?? at(row, "colors", i) });
            if (kind === "plotBars") {
              stroke([{ x: px - barWidth / 2, y: o }, { x: px, y: o }], { color: at(row, "colors", i) });
              stroke([{ x: px, y: cl }, { x: px + barWidth / 2, y: cl }], { color: at(row, "colors", i) });
            } else {
              c.fillStyle = color(at(row, "colors", i)); c.fillRect(px - barWidth / 2, Math.min(o, cl), barWidth, Math.max(1, Math.abs(o - cl)));
              c.strokeStyle = color(at(row, "borderColors", i) ?? at(row, "colors", i)); c.strokeRect(px - barWidth / 2, Math.min(o, cl), barWidth, Math.max(1, Math.abs(o - cl)));
            }
          } else {
            const value = at(row, "values", i); if (value == null || value === false || value === 0) continue;
            const location = text(at(row, "locations", i), "location.abovebar"), below = kind === "plotArrows" ? Number(value) > 0 : location.endsWith("belowbar");
            const py = location.endsWith("top") ? 16 : location.endsWith("bottom") ? height - 12 : location.endsWith("absolute") ? y(value) : y(array(below ? scene.lows : scene.highs)[i]);
            if (py === null) continue;
            const glyph = kind === "plotArrows" ? (below ? "↑" : "↓") : text(at(row, "chars", i));
            c.font = `${fontSize(at(row, "sizes", i))}px sans-serif`; c.textAlign = "center";
            c.fillStyle = color(at(row, kind === "plotArrows" ? (below ? "colorUps" : "colorDowns") : "colors", i));
            c.fillText(glyph, px, py + (below ? 15 : -5));
            c.fillStyle = color(at(row, "textColors", i)); c.fillText(text(at(row, "texts", i)), px, py + (below ? 29 : -19));
          }
        }
      }
      const endpoints = record(scene.endpoints);
      for (const fill of rows(scene.gradients)) {
        const endpoint = (id: unknown, hline: unknown, i: number) => hline ? rows(endpoints.hlines).find((r) => r.id === id)?.price : array(rows(endpoints.plots).find((r) => r.id === id)?.values)[i];
        for (let i = Math.max(1, times.length - (num(fill.showLast) ?? times.length)); i < times.length; i++) {
          const x1 = x(times[i - 1]!), x2 = x(times[i]!); if (x1 === null || x2 === null || x2 < 0 || x1 > width) continue;
          const points = [point({ xloc: "bar_index" }, i - 1, endpoint(fill.firstId, fill.firstIsHLine, i - 1)), point({ xloc: "bar_index" }, i, endpoint(fill.firstId, fill.firstIsHLine, i)),
            point({ xloc: "bar_index" }, i, endpoint(fill.secondId, fill.secondIsHLine, i)), point({ xloc: "bar_index" }, i - 1, endpoint(fill.secondId, fill.secondIsHLine, i - 1))];
          if (points.some((p) => p === null)) continue;
          const gradient = record(array(fill.gradient)[i]), top = y(gradient.topValue), bottom = y(gradient.bottomValue);
          if (top === null || bottom === null) continue;
          const paint = c.createLinearGradient(0, top, 0, bottom); paint.addColorStop(0, color(gradient.topColor, "transparent")); paint.addColorStop(1, color(gradient.bottomColor, "transparent"));
          path(points as Point[], true); c.fillStyle = paint; c.fill();
        }
      }
      c.restore();
    });
  }
}
