import { useEffect, useRef, useState } from "react";
import { t } from "../../i18n/index.js";
import { loadSourcePreferences, saveSourcePreferences } from "./sourcePreferences.js";
import { Icon } from "../../components/icons/Icon.js";
import { Input } from "../../components/ui/Field.js";

interface SourceOption { key: string; label: string; disabled: boolean }

export function SourcePicker({ sources, selected, onSelect }: {
  sources: SourceOption[];
  selected: string;
  onSelect(source: string): void;
}) {
  const [query, setQuery] = useState("");
  const [preferences, setPreferences] = useState(loadSourcePreferences);
  const detailsRef = useRef<HTMLDetailsElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    const dismiss = (event: PointerEvent) => {
      if (detailsRef.current?.open && event.target instanceof Node && !detailsRef.current.contains(event.target)) {
        detailsRef.current.open = false;
      }
    };
    document.addEventListener("pointerdown", dismiss);
    return () => document.removeEventListener("pointerdown", dismiss);
  }, []);
  const update = (next: typeof preferences) => {
    setPreferences(next);
    saveSourcePreferences(next);
  };
  const matches = sources.filter((source) => `${source.key} ${source.label}`.toLowerCase().includes(query.trim().toLowerCase()));
  const favorites = matches.filter((source) => preferences.favorites.includes(source.key));
  const recent = preferences.recent.flatMap((key) => matches.filter((source) => source.key === key && !preferences.favorites.includes(key)));
  const rest = matches.filter((source) => !preferences.favorites.includes(source.key) && !preferences.recent.includes(source.key));
  const groups = [
    { label: t("search.tab.favorites"), items: favorites },
    { label: t("search.recentSources"), items: recent },
    { label: t("interval.tab.all"), items: rest },
  ];
  const selectedLabel = selected ? (sources.find((source) => source.key === selected)?.label || selected) : t("interval.tab.all");
  return <details className="sym-source-picker" ref={detailsRef} onToggle={(event) => {
    if (event.currentTarget.open) { setQuery(""); inputRef.current?.focus(); }
  }}>
    <summary className="ui-input ui-input-sm ui-select sym-source-trigger" aria-label={`${t("search.source")}: ${selectedLabel}`}>
      {selectedLabel}
    </summary>
    <div className="sym-source-panel" onKeyDown={(event) => {
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
      const buttons = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>(".sym-source-option > button:first-child:not(:disabled)"));
      if (!buttons.length) return;
      event.preventDefault();
      const current = buttons.indexOf(document.activeElement as HTMLButtonElement);
      const next = current < 0 ? (event.key === "ArrowDown" ? 0 : buttons.length - 1)
        : (current + (event.key === "ArrowDown" ? 1 : -1) + buttons.length) % buttons.length;
      buttons[next]?.focus();
    }}>
      <Input ref={inputRef} size="sm" type="search" value={query} onChange={(event) => setQuery(event.target.value)}
        aria-label={t("search.sourceSearch")} placeholder={t("search.sourceSearch")} />
      <div className="sym-source-options">
        {!query && <div className="sym-source-option"><button type="button" className="ui-menu-item" aria-pressed={!selected} onClick={() => {
          onSelect("");
          if (detailsRef.current) { detailsRef.current.open = false; detailsRef.current.querySelector("summary")?.focus(); }
        }}>{t("interval.tab.all")}</button></div>}
        {matches.length === 0 && <p className="sym-source-empty">{t("search.noResults")}</p>}
        {groups.filter((group) => group.items.length > 0).map((group) => <section key={group.label}>
          <div className="sym-source-group-title">{group.label}</div>
          {group.items.map((source) => <div className="sym-source-option" key={source.key}>
            <button type="button" className="ui-menu-item" disabled={source.disabled} aria-pressed={selected === source.key}
              onClick={() => {
                update({ ...preferences, recent: [source.key, ...preferences.recent.filter((key) => key !== source.key)].slice(0, 5) });
                onSelect(source.key);
                if (detailsRef.current) { detailsRef.current.open = false; detailsRef.current.querySelector("summary")?.focus(); }
              }}>
              <span className="ui-menu-label">{source.label}</span>
              <span className="ui-menu-hint">{source.key}{source.disabled ? ` ${t("search.unroutable").trim()}` : ""}</span>
              {selected === source.key && <span className="sym-source-check" aria-hidden="true"><Icon name="check" size={12} /></span>}
            </button>
            <button type="button" className="ui-icon-btn ui-icon-btn-sm sym-source-star" aria-pressed={preferences.favorites.includes(source.key)}
              aria-label={`${preferences.favorites.includes(source.key) ? t("search.unfavorite") : t("search.favorite")} ${source.label}`}
              onClick={() => update({ ...preferences, favorites: preferences.favorites.includes(source.key)
                ? preferences.favorites.filter((key) => key !== source.key) : [...preferences.favorites, source.key] })}>
              <Icon name="star" size={12} filled={preferences.favorites.includes(source.key)} />
            </button>
          </div>)}
        </section>)}
      </div>
    </div>
  </details>;
}
