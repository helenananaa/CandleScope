import { useEffect, useState } from "react";
import { t } from "../../i18n/index.js";
import type { SelectedDrawingMeta } from "./drawingSelectionController.js";
import type { DrawingStylePatch } from "./drawingInteractionController.js";
import { changeStyleTemplate, readStyleTemplates, STYLE_TEMPLATE_EVENT, STYLE_TEMPLATE_KEY, styleFamily, type TemplateError } from "./drawingStyleTemplateStore.js";

export default function DrawingStyleTemplates({ drawing, onApply }: {
  drawing: SelectedDrawingMeta;
  onApply(patch: DrawingStylePatch): void;
}) {
  const family = styleFamily(drawing.type);
  const [loaded, setLoaded] = useState(readStyleTemplates);
  const [name, setName] = useState("");
  const [choice, setChoice] = useState("");
  const [error, setError] = useState<TemplateError | null>(null);
  const [status, setStatus] = useState<"saved" | "applied" | "deleted" | null>(null);
  useEffect(() => {
    const refresh = () => setLoaded(readStyleTemplates());
    const external = (event: StorageEvent) => { if (event.key === STYLE_TEMPLATE_KEY || event.key === null) refresh(); };
    window.addEventListener(STYLE_TEMPLATE_EVENT, refresh);
    window.addEventListener("storage", external);
    window.addEventListener("focus", refresh);
    return () => {
      window.removeEventListener(STYLE_TEMPLATE_EVENT, refresh);
      window.removeEventListener("storage", external);
      window.removeEventListener("focus", refresh);
    };
  }, []);
  if (!family) return null;
  const templates = loaded.ok ? loaded.templates.filter((item) => item.family === family) : [];
  const selected = templates.find((item) => item.name === choice);
  const problem = error ?? (!loaded.ok ? loaded.error : null);
  return <details className="drawing-style-templates">
    <summary>{t("drawing.templates.title")}</summary>
    <div className="drawing-template-content">
      <p className="drawing-control-caption">{t("drawing.templates.hint")}</p>
      <label>{t("drawing.templates.select")}<select value={selected?.name ?? ""} onChange={(event) => { setChoice(event.target.value); setStatus(null); setError(null); }}>
        <option value="">{t(templates.length ? "drawing.templates.select" : "drawing.templates.empty")}</option>
        {templates.map((item) => <option key={item.name} value={item.name}>{item.name}</option>)}
      </select></label>
      <div className="drawing-template-actions">
        <button type="button" disabled={!selected} onClick={() => { if (selected) { onApply(selected.style); setStatus("applied"); setError(null); } }}>{t("drawing.templates.apply")}</button>
        <button type="button" disabled={!selected} onClick={() => {
          if (!selected) return;
          const result = changeStyleTemplate({ kind: "delete", family, name: selected.name });
          if (result.ok) { setLoaded(result); setChoice(""); setStatus("deleted"); setError(null); }
          else { setError(result.error); setStatus(null); }
        }}>{t("drawing.templates.delete")}</button>
      </div>
      <label>{t("drawing.templates.name")}<input value={name} maxLength={32} placeholder={t("drawing.templates.name")}
        onChange={(event) => { setName(event.target.value); setError(null); setStatus(null); }} /></label>
      <button type="button" disabled={!name.trim() || !loaded.ok} onClick={() => {
        const result = changeStyleTemplate({ kind: "save", family, name, style: drawing });
        if (result.ok) { setLoaded(result); setChoice(name.trim()); setName(""); setStatus("saved"); setError(null); }
        else { setError(result.error); setStatus(null); }
      }}>{t("drawing.templates.save")}</button>
      {problem && <p className="drawing-field-error" role="alert">{t(`drawing.templates.error.${problem}`)}</p>}
      {status && <p className="drawing-control-caption" role="status">{t(`drawing.templates.${status}`)}</p>}
    </div>
  </details>;
}
