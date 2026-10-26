import type { AlertExpressionDraft } from "../alerts/alertTypes.js";
import { array, bool, choice, object, optional, schema, text } from "./commandSchema.js";
const condition = object({ id: text(128), type: choice(["condition"]), not: bool, left: text(128), comparator: choice(["crossesAbove", "crossesBelow", ">", "<", ">=", "<=", "==", "!=", "between", "outsideRange", "percentChangeAbove", "percentChangeBelow"]), rightType: choice(["number", "field", "indicator"]), rightValue: text(256, 0), rangeMin: text(64, 0), rangeMax: text(64, 0), percentValue: text(64, 0) });
export const alertExpressionDraftSchema = schema<AlertExpressionDraft>({ description: "Bounded expression draft tree. Condition nodes use id/type/not/left/comparator/rightType/rightValue/rangeMin/rangeMax/percentValue; group nodes use id/type='group'/not/op='AND'|'OR'/children. Up to 256 nodes and depth 16.", type: "object" }, (value) => {
  let count = 0;
  const walk = (value: unknown, depth: number): AlertExpressionDraft => {
    if (++count > 256 || depth > 16) throw new Error("EXPRESSION_LIMIT");
    if (value && typeof value === "object" && "type" in value && value.type === "condition") return condition.parse(value);
    return object({ id: text(128), type: choice(["group"]), not: bool, op: choice(["AND", "OR"]), children: array(schema<AlertExpressionDraft>({}, (child) => walk(child, depth + 1)), 256) }).parse(value);
  };
  return walk(value, 0);
});
export const alertDraftPatchSchema = object({ name: optional(text(160, 0)), description: optional(text(2048, 0)), enabled: optional(bool), triggerOn: optional(choice(["realtime", "bar_update", "bar_close"])), expression: optional(alertExpressionDraftSchema),
  maxTriggerMode: optional(choice(["unlimited", "once", "3", "custom"])), customMaxTriggers: optional(text(64, 0)), expiresMode: optional(choice(["never", "1h", "today", "7d", "custom"])), customExpiresAt: optional(text(128, 0)), afterTrigger: optional(choice(["auto-disable", "keep", "pause"])),
  cooldownMode: optional(choice(["always", "30s", "5m", "custom"])), customCooldownSeconds: optional(text(64, 0)), messageTemplate: optional(text(4096, 0)), webhookUrl: optional(text(2048, 0)), channels: optional(object({ in_app: bool, browser: bool, sound: bool, webhook: bool, history: bool })) });
