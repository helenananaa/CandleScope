import type { CSSProperties } from "react";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { chartLinkGroupDisplayName } from "./chartWorkspaceI18n.js";
import { chartLinkGroupDepth } from "./chartWorkspaceLinkModel.js";
import type { ChartCellId, ChartLinkGroupId, ChartWorkspaceDocument } from "./chartWorkspaceTypes.js";

export default function WorkspaceCellLinkSelect({ document, cellId, disabled, onChange, onCreate }: {
  document: ChartWorkspaceDocument;
  cellId: ChartCellId;
  disabled: boolean;
  onChange(cellId: ChartCellId, groupId: ChartLinkGroupId | null): void;
  onCreate(parentId: ChartLinkGroupId | null, cellIds: readonly ChartCellId[]): void;
}) {
  useLocale();
  const groupId = document.cells[cellId]?.linkGroupId ?? null;
  const group = groupId ? document.linkGroups[groupId] : null;
  return (
    <label className="multi-chart-cell-link workspace-cell-link-select"
      data-link-group={groupId ?? "none"}
      style={{ "--chart-link-group-color": group?.color ?? "var(--text-muted)" } as CSSProperties}
      onDoubleClick={(event) => event.stopPropagation()}
    >
      <span aria-hidden="true">↔</span>
      <select aria-label={t("workspace.joinGroup")} disabled={disabled} value={groupId ?? ""}
        title={group ? chartLinkGroupDisplayName(group) : t("workspace.independent")}
        onChange={(event) => {
          const value = event.currentTarget.value;
          if (value === "__new__") onCreate(null, [cellId]);
          else onChange(cellId, value || null);
        }}
      >
        <option value="">{t("workspace.independent")}</option>
        {Object.values(document.linkGroups).map((candidate) => (
          <option key={candidate.id} value={candidate.id}>
            {"— ".repeat(chartLinkGroupDepth(document, candidate.id) - 1)}{chartLinkGroupDisplayName(candidate)}
          </option>
        ))}
        <option value="__new__">{t("workspace.newGroupJoin")}</option>
      </select>
    </label>
  );
}
