import { useId, useMemo } from "react";
import { t } from "../../../i18n/index.js";
import type { NativeResult } from "./nativeBacktestApi.js";
import { nativeDrawings, drawingColor as color, drawingText as text, drawingNumber as num,
  drawingRows, drawingPoint, drawingCellSpan, type DrawingRow } from "./nativeDrawingModel.js";

type Point = { x: number; y: number };
const dash = (style: unknown) => text(style).includes("dotted") ? "2 4" : text(style).includes("dashed") ? "8 5" : undefined;
const sizes: Record<string, number> = { tiny:9,small:11,normal:14,large:18,huge:24 };
const size = (value: unknown) => Math.max(8, Math.min(36, num(value) ?? (sizes[text(value).split(".").at(-1) ?? ""] ?? 13)));

export function NativeDrawingScene({ result }: { result: NativeResult }) {
  const scene = useMemo(() => nativeDrawings(result), [result]);
  const clip = useId().replaceAll(":", "");
  if (!scene.objects.length) return null;
  if (scene.objects.length > 5000) return <p role="status">{t("native.graphics.limit")}</p>;
  const panes = [...new Set(scene.objects.map(({ row }) => text(row.pane,"main")))];
  return <section aria-label={t("native.graphics.title")}><h3>{t("native.graphics.title")}</h3>
    <p>{t("native.graphics.hint")}</p>
    {panes.map((pane) => {
      const objects = scene.objects.filter(({row}) => text(row.pane,"main") === pane);
      const point = (row: DrawingRow, x: unknown, y: unknown) => drawingPoint({ ...row,x,y },result.bars,scene.pine);
      const line = (row: DrawingRow) => [point(row,row.x1,row.y1),point(row,row.x2,row.y2)];
      const polygon = (row: DrawingRow) => drawingRows(row.points).map((p) => point(row,
        p.x ?? (text(row.xloc).endsWith("bar_time") ? p.time : p.index),p.y ?? p.price)).filter((p): p is Point => p !== null);
      const values = objects.flatMap(({kind,row}) => kind === "lines" ? line(row) : kind === "boxes" ?
        [point(row,row.left,row.top),point(row,row.right,row.bottom)] : kind === "polylines" ? polygon(row) :
        kind === "labels" ? [drawingPoint(row,result.bars,scene.pine)] : []).filter((p): p is Point => p !== null);
      if (pane === "main") result.bars.forEach((bar,i) => { values.push({x:i,y:bar.high},{x:i,y:bar.low}); });
      let minimum = Infinity, maximum = -Infinity;
      values.forEach((p) => { minimum=Math.min(minimum,p.y); maximum=Math.max(maximum,p.y); });
      if (!Number.isFinite(minimum)) { minimum=0; maximum=1; }
      const span=maximum-minimum || 1, last=Math.max(1,result.bars.length-1);
      const x = (v: number) => 35+930*v/last, y = (v: number) => 260-230*(v-minimum)/span;
      const linePoints = (row: DrawingRow) => {
        const [a,b]=line(row); if (!a || !b) return null;
        const ext=text(row.extend); const slope=a.x===b.x ? 0 : (b.y-a.y)/(b.x-a.x);
        const lo=a.x<=b.x ? a:b, hi=a.x<=b.x ? b:a;
        return [ext.endsWith("left") || ext.endsWith("both") ? {x:0,y:lo.y-slope*lo.x} : lo,
          ext.endsWith("right") || ext.endsWith("both") ? {x:last,y:hi.y+slope*(last-hi.x)} : hi];
      };
      const paths = new Map(objects.filter(({kind}) => kind==="lines").map(({row}) => [text(row.id),linePoints(row)]));
      const coordinates = (points: Point[]) => points.map((p) => `${x(p.x)},${y(p.y)}`).join(" ");
      const curve = (points: Point[], closed: boolean) => {
        if (!points.length) return "";
        const p=points.map((v) => ({x:x(v.x),y:y(v.y)}));
        if (closed) p.push(p[0]!);
        let d=`M${p[0]!.x},${p[0]!.y}`;
        for (let i=0;i<p.length-1;i++) {
          const a=p[Math.max(0,i-1)]!, b=p[i]!, c=p[i+1]!, e=p[Math.min(p.length-1,i+2)]!;
          d+=` C${b.x+(c.x-a.x)/6},${b.y+(c.y-a.y)/6} ${c.x-(e.x-b.x)/6},${c.y-(e.y-b.y)/6} ${c.x},${c.y}`;
        }
        return d+(closed ? " Z":"");
      };
      return <div key={pane} className="native-drawing-pane"><strong>{pane}</strong>
        {objects.some(({kind}) => kind!=="tables") && <svg viewBox="0 0 1000 290" role="img" aria-label={`${t("native.graphics.title")} · ${pane}`}>
          <defs><clipPath id={`${clip}-${panes.indexOf(pane)}`}><rect x="35" y="10" width="930" height="260" /></clipPath></defs>
          <text x="2" y="25" fill="currentColor" fontSize="10">{maximum.toPrecision(6)}</text>
          <text x="2" y="270" fill="currentColor" fontSize="10">{minimum.toPrecision(6)}</text>
          <g clipPath={`url(#${clip}-${panes.indexOf(pane)})`}>
            {pane==="main" && <polyline points={coordinates(result.bars.map((bar,i) => ({x:i,y:bar.close})))} fill="none" stroke="#94a3b8" opacity="0.3" />}
            {objects.map(({kind,row},i) => {
              const key=`${kind}-${text(row.id)}-${i}`;
              if (kind==="lines") {
                const points=linePoints(row); if (!points) return null;
                return <polyline key={key} points={coordinates(points)} fill="none" stroke={color(row.color)} strokeWidth={num(row.width) ?? 1} strokeDasharray={dash(row.style)} />;
              }
              if (kind==="linefills") {
                const a=paths.get(text(row.line1 ?? row.line1id)),b=paths.get(text(row.line2 ?? row.line2id));
                return a && b ? <polygon key={key} points={coordinates([...a,...[...b].reverse()])} fill={color(row.color,"#38bdf844")} /> : null;
              }
              if (kind==="polylines") {
                const points=polygon(row), closed=row.closed===true;
                return row.curved ? <path key={key} d={curve(points,closed)} stroke={color(row.linecolor)} fill={closed ? color(row.fillcolor,"transparent"):"none"} strokeWidth={num(row.linewidth) ?? 1} strokeDasharray={dash(row.linestyle)} /> :
                  <polyline key={key} points={coordinates(closed && points.length ? [...points,points[0]!] : points)} fill={closed ? color(row.fillcolor,"transparent"):"none"} stroke={color(row.linecolor)} strokeWidth={num(row.linewidth) ?? 1} strokeDasharray={dash(row.linestyle)} />;
              }
              if (kind==="boxes") {
                const a=point(row,row.left,row.top),b=point(row,row.right,row.bottom); if (!a || !b) return null;
                const ext=text(row.extend), left=ext.endsWith("left") || ext.endsWith("both") ? 35:Math.min(x(a.x),x(b.x));
                const right=ext.endsWith("right") || ext.endsWith("both") ? 965:Math.max(x(a.x),x(b.x));
                return <g key={key}><rect x={left} y={Math.min(y(a.y),y(b.y))} width={right-left} height={Math.abs(y(a.y)-y(b.y))}
                  fill={color(row.bgcolor,"transparent")} stroke={color(row.bordercolor)} strokeWidth={num(row.borderwidth) ?? 1} strokeDasharray={dash(row.borderstyle)} />
                  <text x={(left+right)/2} y={(y(a.y)+y(b.y))/2} fill={color(row.textcolor,"#e2e8f0")} textAnchor="middle" fontSize={size(row.textsize)}>{text(row.text)}</text></g>;
              }
              if (kind==="labels") {
                const p=drawingPoint(row,result.bars,scene.pine); if (!p) return null;
                return <g key={key}><title>{text(row.tooltip,row.text as string)}</title>
                  <circle cx={x(p.x)} cy={y(p.y)} r="3" fill={color(row.color)} />
                  <text x={x(p.x)} y={y(p.y)-5} textAnchor="middle" fill={color(row.textcolor,"#e2e8f0")} fontSize={size(row.size)}>{text(row.text)}</text></g>;
              }
              return null;
            })}
          </g>
        </svg>}
        {objects.filter(({kind}) => kind==="tables").map(({row},i) => {
          const columns=num(row.columns) ?? 0, rows=num(row.rows) ?? 0;
          if (rows*columns>10000 || !Number.isInteger(rows) || !Number.isInteger(columns) || rows<0 || columns<0)
            return <p key={i} role="status">{t("native.graphics.limit")}</p>;
          const cells=drawingRows(row.cells), merges=drawingRows(row.merges);
          const byCell=new Map(cells.map((cell) => [`${cell.row}:${cell.column}`,cell]));
          return <div key={i} className="native-table"><table aria-label={`${t("native.graphics.table")} ${text(row.id)}`} style={{background:color(row.bgcolor,"transparent"),border:`${num(row.framewidth) ?? 1}px solid ${color(row.framecolor,"#64748b")}`}}>
            <caption>{text(row.position)}</caption><tbody>{Array.from({length:rows},(_,r) => <tr key={r}>{Array.from({length:columns},(_,c) => {
              const span=drawingCellSpan(r,c,merges); if (span.hidden) return null;
              const cell=byCell.get(`${r}:${c}`) ?? {};
              return <td key={c} rowSpan={span.rowSpan} colSpan={span.colSpan} title={text(cell.tooltip)}
                style={{color:color(cell.textcolor,"#e2e8f0"),background:color(cell.bgcolor,"transparent"),fontSize:size(cell.textsize),whiteSpace:"pre-wrap"}}>{text(cell.text)}</td>;
            })}</tr>)}</tbody></table></div>;
        })}
      </div>;
    })}
  </section>;
}
