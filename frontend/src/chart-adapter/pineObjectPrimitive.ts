import type { ChartTime } from "./chartAdapterTypes.js";
import type { IChartApiBase, ISeriesPrimitive, SeriesAttachedParameter, Logical, IPrimitivePaneRenderer } from "lightweight-charts";
import type { IndicatorDrawing } from "../features/indicators/indicatorTypes.js";
import { drawingColor as color, drawingNumber as num, drawingText as text, drawingRows as rows, drawingCellSpan } from "../features/backtest/native/nativeDrawingModel.js";

type Row = Record<string, unknown>;
type Point = { x: number; y: number };
type Bar = { time: number; high?: number; low?: number };
const normalize = (row: Row): Row => Object.fromEntries(Object.entries(row).map(([key, value]) => [key.replaceAll("_", "").toLowerCase(), value]));
const suffix = (value: unknown) => text(value).split(".").at(-1) || "";
const fontSize = (value: unknown) => Math.min(72, Math.max(8, num(value) ?? ({ tiny: 9, small: 11, normal: 14, large: 18, huge: 24 }[suffix(value)] ?? 13)));
const font = (row: Row, size: number) => `${(num(row.textformatting) ?? 0) & 2 ? "italic " : ""}${(num(row.textformatting) ?? 0) & 1 ? "bold " : ""}${size}px ${suffix(row.textfontfamily) === "monospace" ? "monospace" : "sans-serif"}`;

/** Convert a timestamp to the existing chart's ordinal axis, preserving gaps. */
export function pineTimeLogical(time: number, bars: readonly Bar[]): number | null {
  if (!bars.length || !Number.isFinite(time)) return null;
  let lo = 0, hi = bars.length;
  while (lo < hi) { const mid = (lo + hi) >>> 1; if (bars[mid]!.time < time) lo = mid + 1; else hi = mid; }
  if (bars[lo]?.time === time) return lo;
  const left = Math.max(0, Math.min(bars.length - 2, lo - 1));
  const step = (bars[left + 1]?.time ?? bars[left]!.time + 60) - bars[left]!.time;
  return left + (time - bars[left]!.time) / step;
}
export function pineIndexTime(index: number, times: readonly number[]): number | null {
  if (!times.length || !Number.isFinite(index)) return null;
  const left = Math.max(0, Math.min(times.length - 2, Math.floor(index)));
  return times[left]! + (index - left) * ((times[left + 1] ?? times[left]! + 60) - times[left]!);
}

export class PineObjectPrimitive implements ISeriesPrimitive<ChartTime> {
  private chart: IChartApiBase<ChartTime> | null = null;
  private series: SeriesAttachedParameter<ChartTime>["series"] | null = null;
  private requestUpdate: (() => void) | null = null;
  private scenes: readonly IndicatorDrawing[] = [];
  private bars: readonly Bar[] = [];
  private coordinate: ((time: number) => number | null) | undefined;
  private readonly renderer: IPrimitivePaneRenderer = { draw: (target) => target.useMediaCoordinateSpace((scope) => this.draw(scope.context, scope.mediaSize.width, scope.mediaSize.height)) };
  private readonly view = { zOrder: () => "top" as const, renderer: () => this.renderer };
  attached({ chart, series, requestUpdate }: SeriesAttachedParameter<ChartTime>): void { this.chart = chart; this.series = series; this.requestUpdate = requestUpdate; requestUpdate(); }
  detached(): void { this.chart = null; this.series = null; this.requestUpdate = null; }
  paneViews() { return [this.view]; }
  update(scenes: readonly IndicatorDrawing[], bars: readonly Bar[], coordinate?: (time: number) => number | null) { this.scenes = scenes; this.bars = bars; this.coordinate = coordinate; this.requestUpdate?.(); }
  private timeCoordinate(time: number): number | null {
    if (this.coordinate) return this.coordinate(time);
    const index = pineTimeLogical(time, this.bars);
    return index === null ? null : this.chart!.timeScale().logicalToCoordinate(index as Logical);
  }
  private indexCoordinate(scene: IndicatorDrawing, index: number): number | null {
    if (!scene.times.length) return null;
    const last = scene.times.length - 1;
    if (index < 0 || index > last) {
      const anchor = index < 0 ? 0 : last, x = this.timeCoordinate(scene.times[anchor]!);
      return x === null ? null : x + (index - anchor) * this.chart!.timeScale().options().barSpacing;
    }
    const time = pineIndexTime(index, scene.times);
    return time === null ? null : this.timeCoordinate(time);
  }
  private nativeSamples(scene: IndicatorDrawing, row: Row) {
    const count = Array.isArray(row.values) ? row.values.length : Array.isArray(row.opens) ? row.opens.length : Array.isArray(row.gradient) ? row.gradient.length : 0;
    const offset = num(row.offset) ?? 0, width = this.chart!.timeScale().width(), spacing = this.chart!.timeScale().options().barSpacing;
    const first = Math.max(0, -offset, count - (num(row.showlast) ?? count)), last = Math.min(count, scene.times.length - offset);
    const atX = (i: number) => this.timeCoordinate(scene.times[i + offset]!) ?? -Infinity;
    let lo = first, hi = last;
    while (lo < hi) { const mid = (lo + hi) >>> 1; if (atX(mid) < -spacing) lo = mid + 1; else hi = mid; }
    const samples: Array<{ i: number; x: number; bar: Bar | undefined }> = [];
    for (let i = Math.max(first, lo - 1); i < last; i++) {
      const x = atX(i); if (x > width + spacing) break;
      const index = pineTimeLogical(scene.times[i + offset]!, this.bars);
      samples.push({ i, x, bar: this.bars[Math.round(index ?? -1)] });
    }
    return samples;
  }
  autoscaleInfo(start: Logical, end: Logical) {
    if (!this.chart) return null;
    const scale = this.chart.timeScale(), left = scale.logicalToCoordinate(start), right = scale.logicalToCoordinate(end);
    if (left === null || right === null) return null;
    let minValue = Infinity, maxValue = -Infinity;
    const include = (value: unknown) => { const v = num(value); if (v !== undefined) { minValue = Math.min(minValue, v); maxValue = Math.max(maxValue, v); } };
    for (const scene of this.scenes) for (const { kind, row } of scene.objects) {
      if (kind === "tables" || kind === "linefills") continue;
      if (kind === "plotseries" || kind === "gradientfills") {
        const r = normalize(row);
        for (const { i, bar } of this.nativeSamples(scene, r)) {
          const value = (key: string) => Array.isArray(r[key]) ? r[key][i] : undefined;
          if (kind === "gradientfills") { include(value("firstvalues")); include(value("secondvalues")); }
          else if (r.family === "plotBars" || r.family === "plotCandles") { include(value("highs")); include(value("lows")); }
          else if (suffix(value("locations")) === "absolute") include(value("values"));
          else { include(bar?.high); include(bar?.low); }
        }
        continue;
      }
      const r = normalize(row), coordinates = kind === "lines" ? [r.x1, r.x2] : kind === "boxes" ? [r.left, r.right] : kind === "polylines" ? rows(r.points).map((p) => suffix(r.xloc) === "bar_time" ? p.time : p.index) : [r.x];
      const xs = coordinates.map((value) => {
        const v = num(value); if (v === undefined) return null;
        if (suffix(r.xloc) !== "bar_time") return this.indexCoordinate(scene, v);
        const time = v / 1000;
        if (time === null) return null;
        if (this.coordinate) return this.coordinate(time);
        const logical = pineTimeLogical(time, this.bars);
        return logical === null ? null : scale.logicalToCoordinate(logical as Logical);
      }).filter((v): v is number => v !== null);
      if (!xs.length) continue;
      let lo = xs.reduce((a, b) => Math.min(a, b), Infinity), hi = xs.reduce((a, b) => Math.max(a, b), -Infinity);
      if (["left", "both"].includes(suffix(r.extend))) lo = -Infinity;
      if (["right", "both"].includes(suffix(r.extend))) hi = Infinity;
      if (hi < left || lo > right) continue;
      if (kind === "lines" && xs.length === 2 && xs[0] !== xs[1]) {
        const a = num(r.y1), b = num(r.y2); if (a === undefined || b === undefined) continue;
        for (const px of [Math.max(left, lo), Math.min(right, hi)]) include(a + (b - a) * (px - xs[0]!) / (xs[1]! - xs[0]!));
      } else for (const value of [r.y, r.y1, r.y2, r.top, r.bottom, ...rows(r.points).map((p) => p.price)]) include(value);
    }
    return Number.isFinite(minValue) ? { priceRange: { minValue, maxValue } } : null;
  }
  private draw(ctx: CanvasRenderingContext2D, width: number, height: number): void {
    if (!this.chart || !this.series) return;
    const timeScale = this.chart.timeScale();
    ctx.save(); ctx.beginPath(); ctx.rect(0, 0, width, height); ctx.clip();
    for (const scene of this.scenes) {
      const x = (value: unknown, xloc: unknown) => {
        const v = num(value); if (v === undefined) return null;
        if (suffix(xloc) !== "bar_time") return this.indexCoordinate(scene, v);
        const time = v / 1000;
        if (time !== null && this.coordinate) return this.coordinate(time);
        const logical = time === null ? null : pineTimeLogical(time, this.bars);
        return logical === null ? null : timeScale.logicalToCoordinate(logical as Logical);
      };
      const y = (value: unknown) => { const v = num(value); return v === undefined ? null : this.series!.priceToCoordinate(v); };
      const point = (row: Row, a: unknown, b: unknown): Point | null => { const px = x(a, row.xloc), py = y(b); return px === null || py === null ? null : { x: px, y: py }; };
      const linePoints = (row: Row): Point[] => {
        let a = point(row, row.x1, row.y1), b = point(row, row.x2, row.y2);
        if (!a || !b) return [];
        if (a.x > b.x) [a, b] = [b, a];
        const extension = suffix(row.extend), dx = b.x - a.x, dy = b.y - a.y;
        if (dx === 0) return extension === "none" || !extension ? [a, b] : [{ x: a.x, y: 0 }, { x: b.x, y: height }];
        return [extension === "left" || extension === "both" ? { x: 0, y: a.y - a.x * dy / dx } : a,
          extension === "right" || extension === "both" ? { x: width, y: b.y + (width - b.x) * dy / dx } : b];
      };
      const order = { gradientfills: -1, linefills: 0, boxes: 1, polylines: 2, lines: 3, plotseries: 4, labels: 5, tables: 6 };
      const objects = scene.objects.map(({ kind, row }) => ({ kind, row: normalize(row) })).sort((a, b) => order[a.kind] - order[b.kind]);
      const lines = new Map(objects.filter(({ kind }) => kind === "lines").map(({ row }) => [text(row.id), linePoints(row)]));
      const path = (points: Point[], closed: boolean, curved = false) => {
        if (!points.length) return;
        ctx.beginPath(); ctx.moveTo(points[0]!.x, points[0]!.y);
        const count = closed ? points.length : points.length - 1;
        for (let i = 0; i < count; i++) {
          const b = points[i]!, c = points[(i + 1) % points.length]!;
          if (!curved) { ctx.lineTo(c.x, c.y); continue; }
          const a = points[closed ? (i + points.length - 1) % points.length : Math.max(0, i - 1)]!;
          const d = points[closed ? (i + 2) % points.length : Math.min(points.length - 1, i + 2)]!;
          ctx.bezierCurveTo(b.x + (c.x - a.x) / 6, b.y + (c.y - a.y) / 6, c.x - (d.x - b.x) / 6, c.y - (d.y - b.y) / 6, c.x, c.y);
        }
        if (closed) ctx.closePath();
      };
      for (const { kind, row } of objects) {
        ctx.save();
        const style = suffix(row.style ?? row.linestyle ?? row.borderstyle).replace(/^style_/, "");
        ctx.setLineDash(style.includes("dotted") ? [2, 4] : style.includes("dashed") ? [8, 5] : []);
        ctx.lineWidth = Math.min(20, Math.max(0, num(row.width ?? row.linewidth ?? row.borderwidth) ?? 1));
        if (kind === "plotseries") this.drawNativeSeries(ctx, scene, row, height);
        else if (kind === "gradientfills") this.drawGradient(ctx, scene, row);
        else if (kind === "lines") {
          const points = linePoints(row); path(points, false); ctx.strokeStyle = color(row.color, "transparent"); ctx.stroke();
          const arrow = (tip: Point, from: Point) => { const angle = Math.atan2(tip.y - from.y, tip.x - from.x), length = 7 + ctx.lineWidth; ctx.beginPath(); ctx.moveTo(tip.x - length * Math.cos(angle - .4), tip.y - length * Math.sin(angle - .4)); ctx.lineTo(tip.x, tip.y); ctx.lineTo(tip.x - length * Math.cos(angle + .4), tip.y - length * Math.sin(angle + .4)); ctx.stroke(); };
          if (points.length === 2 && (style === "arrow_left" || style === "arrow_both")) arrow(points[0]!, points[1]!);
          if (points.length === 2 && (style === "arrow_right" || style === "arrow_both")) arrow(points[1]!, points[0]!);
        } else if (kind === "linefills") {
          const a = lines.get(text(row.line1)), b = lines.get(text(row.line2));
          if (a?.length && b?.length) { path([...a, ...[...b].reverse()], true); ctx.fillStyle = color(row.color, "transparent"); ctx.fill(); }
        } else if (kind === "polylines") {
          const points = rows(row.points).map(normalize).map((p) => point(row, suffix(row.xloc) === "bar_time" ? p.time : p.index, p.price)).filter((p): p is Point => p !== null);
          path(points, row.closed === true, row.curved === true);
          ctx.fillStyle = color(row.fillcolor, "transparent"); if (row.fillcolor != null) ctx.fill();
          ctx.strokeStyle = color(row.linecolor, "transparent"); ctx.stroke();
        } else if (kind === "boxes") {
          const a = point(row, row.left, row.top), b = point(row, row.right, row.bottom);
          if (a && b) {
            const extension = suffix(row.extend), left = extension === "left" || extension === "both" ? 0 : Math.min(a.x, b.x), right = extension === "right" || extension === "both" ? width : Math.max(a.x, b.x);
            const top = Math.min(a.y, b.y), bottom = Math.max(a.y, b.y);
            ctx.fillStyle = color(row.bgcolor, "transparent"); ctx.fillRect(left, top, right - left, bottom - top);
            ctx.strokeStyle = color(row.bordercolor, "transparent"); if (ctx.lineWidth) ctx.strokeRect(left, top, right - left, bottom - top);
            this.drawText(ctx, row, text(row.text), left, top, right - left, bottom - top);
          }
        } else if (kind === "labels") {
          const px = x(row.x, row.xloc); let py: number | null = y(row.y);
          const index = suffix(row.xloc) === "bar_time" ? pineTimeLogical((num(row.x) ?? 0) / 1000, this.bars) : pineTimeLogical(pineIndexTime(num(row.x) ?? 0, scene.times) ?? 0, this.bars);
          const bar = this.bars[Math.round(index ?? -1)];
          const above = suffix(row.yloc) === "abovebar", below = suffix(row.yloc) === "belowbar";
          if (bar && (above || below)) { const coordinate = y(above ? bar.high : bar.low); py = coordinate === null ? null : coordinate + (above ? -12 : 12); }
          if (px !== null && py !== null) this.drawLabel(ctx, row, px, py);
        } else if (kind === "tables") this.drawTable(ctx, row, width, height);
        ctx.restore();
      }
    }
    ctx.restore();
  }
  private drawNativeSeries(ctx: CanvasRenderingContext2D, scene: IndicatorDrawing, row: Row, paneHeight: number) {
    const spacing = this.chart!.timeScale().options().barSpacing, half = Math.max(1, spacing * .35);
    const at = (key: string, index: number) => Array.isArray(row[key]) ? row[key][index] : undefined;
    const py = (value: unknown) => { const v = num(value); return v === undefined ? null : this.series!.priceToCoordinate(v); };
    for (const { i, x, bar } of this.nativeSamples(scene, row)) {
      if (!Number.isFinite(x)) continue;
      if (row.family === "plotBars" || row.family === "plotCandles") {
        const open = py(at("opens", i)), high = py(at("highs", i)), low = py(at("lows", i)), close = py(at("closes", i));
        if (open === null || high === null || low === null || close === null) continue;
        const bodyColor = color(at("colors", i), "#2962ff");
        ctx.lineWidth = 1; ctx.strokeStyle = row.family === "plotBars" ? bodyColor : color(at("wickcolors", i), bodyColor);
        ctx.beginPath(); ctx.moveTo(x, high); ctx.lineTo(x, low); ctx.stroke();
        if (row.family === "plotBars") { ctx.beginPath(); ctx.moveTo(x - half, open); ctx.lineTo(x, open); ctx.moveTo(x, close); ctx.lineTo(x + half, close); ctx.stroke(); }
        else { const top = Math.min(open, close), h = Math.max(1, Math.abs(close - open)); ctx.fillStyle = bodyColor; ctx.fillRect(x - half, top, half * 2, h); ctx.strokeStyle = color(at("bordercolors", i), bodyColor); ctx.strokeRect(x - half, top, half * 2, h); }
        continue;
      }
      const value = at("values", i);
      if (value === null || value === undefined || value === false || value === 0) continue;
      const up = (num(value) ?? 0) > 0, location = suffix(at("locations", i));
      let y: number | null = location === "absolute" ? py(value) : location === "top" ? 16 : location === "bottom" ? paneHeight - 16 : py(location === "belowbar" || row.family === "plotArrows" && up ? bar?.low : bar?.high);
      if (y === null) continue;
      if (location !== "absolute" && location !== "top" && location !== "bottom") y += location === "belowbar" || row.family === "plotArrows" && up ? 12 : -12;
      if (row.family === "plotArrows") {
        const minimum = num(at("minheights", i)) || 5, maximum = num(at("maxheights", i)) || 30;
        const h = minimum + (maximum - minimum) * Math.abs(num(value) ?? 0) / (num(row.arrowmaximum) || 1), direction = up ? 1 : -1;
        ctx.strokeStyle = color(at(up ? "colorups" : "colordowns", i), up ? "#26a69a" : "#ef5350"); ctx.lineWidth = 2;
        ctx.beginPath(); ctx.moveTo(x, y + h * direction); ctx.lineTo(x, y); ctx.moveTo(x - 4, y + 5 * direction); ctx.lineTo(x, y); ctx.lineTo(x + 4, y + 5 * direction); ctx.stroke();
      } else {
        const size = fontSize(at("sizes", i)); ctx.font = `${size}px sans-serif`; ctx.textAlign = "center"; ctx.textBaseline = "middle";
        ctx.fillStyle = color(at("colors", i), "#2962ff"); ctx.fillText(text(at("chars", i)), x, y);
        ctx.fillStyle = color(at("textcolors", i), "#d1d5db"); ctx.fillText(text(at("texts", i)), x, y + size + 2);
      }
    }
  }
  private drawGradient(ctx: CanvasRenderingContext2D, scene: IndicatorDrawing, row: Row) {
    const at = (key: string, index: number) => Array.isArray(row[key]) ? row[key][index] : undefined;
    let previous: { x: number; a: number; b: number } | null = null;
    for (const { i, x } of this.nativeSamples(scene, row)) {
      const a = num(at("firstvalues", i)), b = num(at("secondvalues", i));
      const raw = at("gradient", i), gradient = raw && typeof raw === "object" ? normalize(raw as Row) : {};
      const top = num(gradient.topvalue), bottom = num(gradient.bottomvalue);
      if (a === undefined || b === undefined || top === undefined || bottom === undefined) { if (row.fillgaps === false) previous = null; continue; }
      const ya = this.series!.priceToCoordinate(a), yb = this.series!.priceToCoordinate(b), yt = this.series!.priceToCoordinate(top), ybottom = this.series!.priceToCoordinate(bottom);
      if (ya === null || yb === null || yt === null || ybottom === null) continue;
      if (previous) {
        const paint = ctx.createLinearGradient(0, yt, 0, ybottom === yt ? yt + 1 : ybottom);
        paint.addColorStop(0, color(gradient.topcolor, "transparent")); paint.addColorStop(1, color(gradient.bottomcolor, "transparent"));
        ctx.fillStyle = paint; ctx.beginPath(); ctx.moveTo(previous.x, previous.a); ctx.lineTo(x, ya); ctx.lineTo(x, yb); ctx.lineTo(previous.x, previous.b); ctx.closePath(); ctx.fill();
      }
      previous = { x, a: ya, b: yb };
    }
  }
  private drawText(ctx: CanvasRenderingContext2D, row: Row, value: string, left: number, top: number, width: number, height: number) {
    const size = fontSize(row.textsize ?? row.size); ctx.font = font(row, size); ctx.fillStyle = color(row.textcolor, "#d1d5db");
    const halign = suffix(row.texthalign ?? row.textalign), valign = suffix(row.textvalign);
    const align = halign === "left" ? "left" : halign === "right" ? "right" : "center";
    ctx.textAlign = align; ctx.textBaseline = "middle";
    let lines = value.split("\n");
    if (suffix(row.textwrap) === "wrap_auto" && width > 0) lines = lines.flatMap((line) => { const result: string[] = []; let current = ""; for (const char of line) { if (current && ctx.measureText(current + char).width > width - 8) { result.push(current); current = ""; } current += char; } result.push(current); return result; });
    const x = align === "left" ? left + 4 : align === "right" ? left + width - 4 : left + width / 2;
    const start = valign === "top" ? top + size / 2 + 3 : valign === "bottom" ? top + height - size * (lines.length - .5) - 3 : top + height / 2 - size * (lines.length - 1) / 2;
    ctx.save(); ctx.beginPath(); ctx.rect(left, top, Math.max(0, width), Math.max(0, height)); ctx.clip();
    lines.forEach((line, index) => ctx.fillText(line, x, start + size * index)); ctx.restore();
  }
  private drawLabel(ctx: CanvasRenderingContext2D, row: Row, x: number, y: number) {
    const size = fontSize(row.size); ctx.font = font(row, size);
    const value = text(row.text), style = suffix(row.style).replace(/^style_/, ""), lines = value.split("\n"), width = Math.max(8, ...lines.map((line) => ctx.measureText(line).width)) + 10, height = size * lines.length + 8;
    let left = x - width / 2, top = y - height / 2;
    if (style.includes("down")) top = y - height - 6;
    if (style.includes("up")) top = y + 6;
    if (style.includes("left")) left = x + 6;
    if (style.includes("right")) left = x - width - 6;
    ctx.fillStyle = color(row.color, "transparent");
    if (style.includes("label_")) { ctx.beginPath(); ctx.moveTo(x, y); ctx.lineTo(left + width / 2 - 4, top + height / 2); ctx.lineTo(left + width / 2 + 4, top + height / 2); ctx.fill(); ctx.fillRect(left, top, width, height); }
    else if (style === "circle" || style === "xcross" || style === "cross" || style === "square" || style === "diamond" || style.includes("arrow") || style.includes("triangle") || style === "flag") {
      ctx.beginPath(); const r = Math.max(3, size / 2);
      if (style === "circle") ctx.arc(x, y, r, 0, Math.PI * 2);
      else if (style === "square") ctx.rect(x - r, y - r, r * 2, r * 2);
      else if (style === "cross" || style === "xcross") { ctx.strokeStyle = ctx.fillStyle; const d = style === "cross" ? 0 : r; ctx.moveTo(x - r, y - d); ctx.lineTo(x + r, y + d); ctx.moveTo(x - d, y + r); ctx.lineTo(x + d, y - r); ctx.stroke(); }
      else if (style === "diamond") { ctx.moveTo(x, y - r); ctx.lineTo(x + r, y); ctx.lineTo(x, y + r); ctx.lineTo(x - r, y); ctx.closePath(); }
      else if (style === "flag") { ctx.moveTo(x, y + r); ctx.lineTo(x, y - r); ctx.lineTo(x + r * 1.5, y - r / 2); ctx.lineTo(x, y); ctx.closePath(); }
      else { const direction = style.includes("down") ? 1 : -1; ctx.moveTo(x, y + r * direction); ctx.lineTo(x - r, y); ctx.lineTo(x - r / 3, y); if (style.includes("arrow")) { ctx.lineTo(x - r / 3, y - r * direction); ctx.lineTo(x + r / 3, y - r * direction); ctx.lineTo(x + r / 3, y); } ctx.lineTo(x + r, y); ctx.closePath(); }
      ctx.fill();
    }
    this.drawText(ctx, { ...row, textsize: size }, value, left, top, width, height);
  }
  private drawTable(ctx: CanvasRenderingContext2D, row: Row, width: number, height: number) {
    const columns = num(row.columns) ?? 0, count = num(row.rows) ?? 0;
    if (!Number.isInteger(columns) || !Number.isInteger(count) || columns <= 0 || count <= 0 || columns * count > 10000) return;
    const cells = rows(row.cells).map(normalize), merges = rows(row.mergedcells).map(normalize), byCell = new Map(cells.map((cell) => [`${cell.row}:${cell.column}`, cell]));
    const widths = Array.from({ length: columns }, () => 12), heights = Array.from({ length: count }, () => 20);
    for (const cell of cells) {
      const c = num(cell.column) ?? -1, r = num(cell.row) ?? -1; if (c < 0 || c >= columns || r < 0 || r >= count) continue;
      const size = fontSize(cell.textsize); ctx.font = font(cell, size);
      const span = drawingCellSpan(r, c, merges); if (span.hidden) continue;
      const desired = num(cell.width) ? width * Number(cell.width) / 100 : Math.max(...text(cell.text).split("\n").map((line) => ctx.measureText(line).width), 4) + 10;
      for (let i = c; i < Math.min(columns, c + (span.colSpan ?? 1)); i++) widths[i] = Math.max(widths[i]!, desired / (span.colSpan ?? 1));
      heights[r] = Math.max(heights[r]!, num(cell.height) ? height * Number(cell.height) / 100 : size * text(cell.text).split("\n").length + 8);
    }
    const totalWidth = widths.reduce((a, b) => a + b, 0), totalHeight = heights.reduce((a, b) => a + b, 0), position = suffix(row.position);
    const left = position.includes("left") ? 8 : position.includes("right") ? width - totalWidth - 8 : (width - totalWidth) / 2;
    const top = position.includes("top") ? 8 : position.includes("bottom") ? height - totalHeight - 8 : (height - totalHeight) / 2;
    ctx.fillStyle = color(row.bgcolor, "transparent"); ctx.fillRect(left, top, totalWidth, totalHeight);
    for (let r = 0, y = top; r < count; y += heights[r]!, r++) for (let c = 0, x = left; c < columns; x += widths[c]!, c++) {
      const span = drawingCellSpan(r, c, merges); if (span.hidden) continue;
      const cell = byCell.get(`${r}:${c}`) || {}, w = widths.slice(c, c + (span.colSpan ?? 1)).reduce((a, b) => a + b, 0), h = heights.slice(r, r + (span.rowSpan ?? 1)).reduce((a, b) => a + b, 0);
      ctx.fillStyle = color(cell.bgcolor, "transparent"); ctx.fillRect(x, y, w, h);
      ctx.lineWidth = num(row.borderwidth) ?? 0; ctx.strokeStyle = color(row.bordercolor, "transparent"); if (ctx.lineWidth) ctx.strokeRect(x, y, w, h);
      this.drawText(ctx, cell, text(cell.text), x, y, w, h);
    }
    ctx.lineWidth = num(row.framewidth) ?? 0; ctx.strokeStyle = color(row.framecolor, "transparent"); if (ctx.lineWidth) ctx.strokeRect(left, top, totalWidth, totalHeight);
  }
}
