import { useState, type CSSProperties } from "react";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { visibleCellIds } from "./chartWorkspaceLayout.js";
import { chartLinkGroupDisplayName } from "./chartWorkspaceI18n.js";
import WorkspaceCellLinkSelect from "./WorkspaceCellLinkSelect.js";
import type { ChartCellId, ChartLinkGroup } from "./chartWorkspaceTypes.js";
import type { ChartWorkspaceRuntime } from "./useChartWorkspaceRuntime.js";

export default function WorkspaceLinkMembers({ runtime, groups }: {
  runtime: ChartWorkspaceRuntime;
  groups: readonly ChartLinkGroup[];
}) {
  useLocale();
  const { view, actions } = runtime;
  const [selected, setSelected] = useState<ChartCellId[]>([]);
  const members = Object.values(view.document.windows).flatMap((window, windowIndex) => (
    visibleCellIds(window.layoutTree).flatMap((id, index) => {
      const cell = view.document.cells[id];
      return cell ? [{ cell, index, windowIndex }] : [];
    })
  ));
  const ids = members.map(({ cell }) => cell.id);
  const selectedIds = ids.filter((id) => selected.includes(id));
  const toggle = (targets: ChartCellId[]) => setSelected((previous) => (
    targets.every((id) => previous.includes(id))
      ? previous.filter((id) => !targets.includes(id))
      : [...new Set([...previous, ...targets])]
  ));

  return (
    <section className="workspace-panel-section workspace-link-members">
      <div className="workspace-panel-section-heading">
        <div><h3>{t("workspace.members")}</h3><p>{t("workspace.membersHint")}</p></div>
      </div>
      <div className="workspace-member-bulk">
        <label><input type="checkbox" disabled={!view.ready || !ids.length}
          checked={ids.length > 0 && selectedIds.length === ids.length}
          onChange={() => toggle(ids)} />{t("workspace.selectAllCharts")}</label>
        <select aria-label={t("workspace.moveSelected", { count: selectedIds.length })}
          value="" disabled={!view.ready || !selectedIds.length}
          onChange={(event) => {
            const value = event.currentTarget.value;
            if (!value) return;
            if (value === "__new__") actions.createLinkGroup(null, selectedIds);
            else actions.setCellsLinkGroup(selectedIds, value === "__none__" ? null : value);
            setSelected([]);
          }}>
          <option value="" disabled>{t("workspace.moveSelected", { count: selectedIds.length })}</option>
          <option value="__none__">{t("workspace.independent")}</option>
          {groups.map((group) => <option key={group.id} value={group.id}>{chartLinkGroupDisplayName(group)}</option>)}
          <option value="__new__">{t("workspace.newGroupJoin")}</option>
        </select>
      </div>
      {[null, ...groups].map((group) => {
        const rows = members.filter(({ cell }) => cell.linkGroupId === (group?.id ?? null));
        return (
          <fieldset key={group?.id ?? "independent"} disabled={!view.ready}
            style={{ "--chart-link-group-color": group?.color ?? "var(--text-muted)" } as CSSProperties}>
            <legend><label><input type="checkbox" disabled={!rows.length}
              checked={rows.length > 0 && rows.every(({ cell }) => selectedIds.includes(cell.id))}
              onChange={() => toggle(rows.map(({ cell }) => cell.id))} />
              {group ? chartLinkGroupDisplayName(group) : t("workspace.independent")} · {rows.length}
            </label></legend>
            {rows.map(({ cell, index, windowIndex }) => (
              <div key={cell.id} className="workspace-member-row">
                <label>
                  <input type="checkbox" checked={selectedIds.includes(cell.id)} onChange={() => toggle([cell.id])} />
                  <span><strong>{cell.session.symbol} · {cell.session.interval}</strong>
                    <small>{t("workspace.memberLocation", { window: windowIndex + 1, chart: index + 1 })}
                      {" · "}{cell.session.exchange} · {cell.session.marketType}</small>
                  </span>
                </label>
                <WorkspaceCellLinkSelect document={view.document} cellId={cell.id} disabled={!view.ready}
                  onChange={actions.setCellLinkGroup} onCreate={actions.createLinkGroup} />
              </div>
            ))}
          </fieldset>
        );
      })}
    </section>
  );
}
