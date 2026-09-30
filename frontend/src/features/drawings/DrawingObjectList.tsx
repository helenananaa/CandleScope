import { useRef, useState, useSyncExternalStore } from "react";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import type { DrawingEngineApi } from "./DrawingEngineHost.js";
import type { DrawingObjectApi } from "./drawingObjectApi.js";
import { savedDrawingFromEntity } from "./core/drawingCodec.js";
import { drawingName } from "./drawingObjectLabels.js";
import { drawingVisibleAtInterval } from "./drawingVisibility.js";
import { StyleIcon } from "./DrawingStyleInputs.js";
import { useDrawingSurfacePlacement } from "./useDrawingEditorLayout.js";

type ObjectFilter = "all" | "hidden" | "locked" | "otherIntervals";

function ObjectGroup({ api, label, interval, query, filter, close }: {
  api: DrawingObjectApi; label: string; interval: string; query: string; filter: ObjectFilter; close(): void;
}) {
  const document = useSyncExternalStore(api.subscribeObjectDocument, api.getObjectDocument, api.getObjectDocument);
  const [failed, setFailed] = useState(false);
  const run = (action: () => boolean) => { const ok = action(); setFailed(!ok); return ok; };
  const words = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const objects = [...document.zOrder].reverse().flatMap(id => {
    const entity = document.entities.get(id);
    const drawing = entity && savedDrawingFromEntity(entity);
    if (!drawing) return [];
    const typeName = drawing.type === "text" ? t("drawing.objects.text")
      : drawingName(drawing.type === "shape" ? drawing.shapeType ?? "rectangle"
        : drawing.type === "line" ? drawing.lineType ?? "line"
        : drawing.type === "axis-line" ? drawing.axisLineType ?? "horizontal-line" : drawing.type);
    const name = drawing.type === "text" ? drawing.text || typeName : typeName;
    const intervalHidden = !drawingVisibleAtInterval({ visibleIntervals: drawing.visibleIntervals ?? null }, interval);
    const searchable = `${typeName} ${name} ${id}`.toLocaleLowerCase();
    if (!words.every(word => searchable.includes(word))) return [];
    if (filter === "hidden" && !drawing.hidden) return [];
    if (filter === "locked" && !drawing.locked) return [];
    if (filter === "otherIntervals" && !intervalHidden) return [];
    return [{ id, drawing, name, intervalHidden }];
  });
  const filtering = words.length > 0 || filter !== "all";
  return <section aria-label={label} className="drawing-object-group">
    <h4>{label}<span aria-live="polite">{filtering ? `${objects.length} / ${document.zOrder.length}` : document.zOrder.length}</span></h4>
    {objects.length === 0 && <p className="drawing-control-caption">{t(document.zOrder.length === 0 ? "drawing.objects.empty" : "drawing.objects.noMatches")}</p>}
    <ul>{objects.map(({ id, drawing, name, intervalHidden }) => {
      return <li key={id} data-drawing-object={id}>
        <div className="drawing-object-row">
          <button className="drawing-object-select" type="button" disabled={drawing.hidden || intervalHidden}
            title={name} onClick={() => { if (run(() => api.selectObject(id))) close(); }}>
            <span className="drawing-object-swatch" style={{ backgroundColor: "color" in drawing ? drawing.color : undefined }} />
            <span><strong>{name}</strong><small>{id}{drawing.hidden ? ` · ${t("drawing.objects.hidden")}` : ""}</small></span>
          </button>
          <button type="button" aria-label={t("drawing.objects.front")} title={t("drawing.objects.front")}
            disabled={document.zOrder.at(-1) === id} onClick={() => run(() => api.reorderObject(id, "front"))}>
            <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M4 4h16M12 20V8m-5 5 5-5 5 5" /></svg>
          </button>
          <button type="button" aria-label={t("drawing.objects.back")} title={t("drawing.objects.back")}
            disabled={document.zOrder[0] === id} onClick={() => run(() => api.reorderObject(id, "back"))}>
            <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M4 20h16M12 4v12m-5-5 5 5 5-5" /></svg>
          </button>
          <button type="button" aria-label={t(drawing.hidden ? "drawing.objects.show" : "drawing.objects.hide")} aria-pressed={!!drawing.hidden}
            title={t(drawing.hidden ? "drawing.objects.show" : "drawing.objects.hide")} onClick={() => run(() => api.updateObject(id, { hidden: !drawing.hidden }))}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12Z" /><circle cx="12" cy="12" r="3" />{drawing.hidden && <path d="m3 3 18 18" />}</svg>
          </button>
          <button type="button" aria-label={t(drawing.locked ? "drawing.editor.unlock" : "drawing.editor.lock")} aria-pressed={!!drawing.locked}
            title={t(drawing.locked ? "drawing.editor.unlock" : "drawing.editor.lock")} onClick={() => run(() => api.updateObject(id, { locked: !drawing.locked }))}><StyleIcon name={drawing.locked ? "lock" : "unlock"} /></button>
          <button type="button" aria-label={t("format.delete")} title={t("format.delete")} onClick={() => run(() => api.deleteObject(id))}><StyleIcon name="delete" /></button>
        </div>
        {intervalHidden && <div className="drawing-object-interval"><span>{t("drawing.objects.otherIntervals")}</span>
          <button type="button" onClick={() => run(() => api.updateObject(id, { visibleIntervals: null }))}>{t("drawing.visibility.all")}</button></div>}
      </li>;
    })}</ul>
    {failed && <p role="alert" className="drawing-control-caption">{t("drawing.objects.failed")}</p>}
  </section>;
}

export default function DrawingObjectList({ apis, currentInterval, panes, onSelectPane }: {
  apis: ReadonlyMap<string, DrawingEngineApi>; currentInterval: string;
  panes: readonly { id: string; label: string }[];
  onSelectPane(paneId: string): void;
}) {
  useLocale();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<ObjectFilter>("all");
  const trigger = useRef<HTMLButtonElement>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const placement = useDrawingSurfacePlacement(dialog, trigger, open);
  const sources = [{ id: "main", label: t("drawing.objects.main") }, ...panes]
    .flatMap(pane => { const api = apis.get(pane.id)?.objects; return api ? [{ ...pane, api }] : []; });
  const close = () => { dialog.current?.close(); setOpen(false); setQuery(""); setFilter("all"); trigger.current?.focus(); };
  if (!sources.length) return null;
  return <div className="drawing-object-list" onPointerDown={event => event.stopPropagation()}
    onMouseDown={event => event.stopPropagation()} onClick={event => event.stopPropagation()} onDoubleClick={event => event.stopPropagation()}
    onKeyDown={event => event.stopPropagation()} onWheel={event => event.stopPropagation()}>
    <button className="drawing-object-trigger" ref={trigger} type="button" aria-label={t("drawing.objects.title")}
      title={t("drawing.objects.title")} aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen(true)}>
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="m3 7 9-5 9 5-9 5-9-5Zm0 5 9 5 9-5M3 17l9 5 9-5" /></svg>
    </button>
    {open && <dialog ref={dialog} className="drawing-properties-panel drawing-object-panel" style={placement}
      aria-label={t("drawing.objects.title")} onCancel={event => { event.preventDefault(); close(); }}>
      <header className="drawing-properties-header"><div><span className="drawing-control-caption">{t("drawing.objects.hint")}</span><h3>{t("drawing.objects.title")}</h3></div>
        <button type="button" aria-label={t("settings.close")} onClick={close}><StyleIcon name="close" /></button></header>
      <div className="drawing-object-search">
        <input type="search" aria-label={t("drawing.objects.search")} placeholder={t("drawing.objects.search")}
          value={query} onChange={event => setQuery(event.target.value)} />
        {(query || filter !== "all") && <button type="button" onClick={() => { setQuery(""); setFilter("all"); }}>{t("drawing.objects.reset")}</button>}
      </div>
      <div className="drawing-object-filters" role="group" aria-label={t("drawing.objects.filter")}>
        {(["all", "hidden", "locked", "otherIntervals"] as const).map(value => <button key={value} type="button"
          aria-pressed={filter === value} onClick={() => setFilter(value)}>{t(`drawing.objects.${value}`)}</button>)}
      </div>
      <div className="drawing-object-content">{sources.map(source => <ObjectGroup key={`${source.id}:${source.api.getObjectDocument().scopeKey}`}
        api={source.api} label={source.label} interval={currentInterval} query={query} filter={filter} close={() => { onSelectPane(source.id); close(); }} />)}</div>
      <footer className="drawing-properties-footer"><span className="drawing-control-caption">{t("drawing.objects.undoHint")}</span></footer>
    </dialog>}
  </div>;
}
