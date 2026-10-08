import { t, type MessageKey } from "../../i18n/index.js";
import {
  DEFAULT_CHART_LINK_GROUP_ID,
  type ChartLinkGroup,
  type ChartWorkspaceLayout,
} from "./chartWorkspaceTypes.js";

const LAYOUT_LABEL_KEYS: Record<ChartWorkspaceLayout, MessageKey> = {
  single: "workspace.template.single",
  "split-vertical": "workspace.template.splitVertical",
  "split-horizontal": "workspace.template.splitHorizontal",
  "main-confirmation": "workspace.template.mainConfirm",
  quad: "workspace.template.quad",
  "grid-6": "workspace.template.grid6",
  "grid-8": "workspace.template.grid8",
  "grid-9": "workspace.template.grid9",
  "grid-12": "workspace.template.grid12",
  "grid-16": "workspace.template.grid16",
  custom: "workspace.layout.custom",
};

export function chartWorkspaceLayoutLabel(layout: ChartWorkspaceLayout): string {
  return t(LAYOUT_LABEL_KEYS[layout]);
}

const DEFAULT_CONTROLLER_NAMES = new Set(["Controller group", "主控组"]);
const NUMBERED_GROUP_NAME = /^(?:Link group|联动组)\s+(\d+)$/;

export function chartLinkGroupDisplayName(
  group: Pick<ChartLinkGroup, "id" | "name">,
): string {
  if (
    group.id === DEFAULT_CHART_LINK_GROUP_ID
    && DEFAULT_CONTROLLER_NAMES.has(group.name)
  ) {
    return t("workspace.linkGroup.controller");
  }
  const numbered = NUMBERED_GROUP_NAME.exec(group.name);
  return numbered
    ? t("workspace.linkGroup.numbered", { count: Number(numbered[1]) })
    : group.name;
}
