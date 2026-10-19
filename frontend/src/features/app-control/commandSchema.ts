/** Small, strict JSON contracts shared by discovery and execution. No reflective invocation. */
export interface CommandSchema<T> { jsonSchema: Record<string, unknown>; parse(value: unknown): T }
type Parsed<S> = S extends CommandSchema<infer T> ? T : never;
type ObjectParsed<S extends Record<string, CommandSchema<unknown>>> =
  { [K in keyof S as undefined extends Parsed<S[K]> ? never : K]: Parsed<S[K]> }
  & { [K in keyof S as undefined extends Parsed<S[K]> ? K : never]?: Exclude<Parsed<S[K]>, undefined> };
export function schema<T>(jsonSchema: Record<string, unknown>, parse: (value: unknown) => T): CommandSchema<T> { return { jsonSchema, parse }; }
function invalid(message = "Invalid command arguments"): never { throw new Error(message); }
export const text = (maxLength = 256, minLength = 1) => schema<string>({ type: "string", minLength, maxLength }, (v) =>
  typeof v === "string" && v.length >= minLength && v.length <= maxLength ? v : invalid());
export const bool = schema<boolean>({ type: "boolean" }, (v) => typeof v === "boolean" ? v : invalid());
export const number = (minimum = -1e15, maximum = 1e15, integer = false) => schema<number>({ type: integer ? "integer" : "number", minimum, maximum }, (v) =>
  typeof v === "number" && Number.isFinite(v) && (!integer || Number.isSafeInteger(v)) && v >= minimum && v <= maximum ? v : invalid());
export const choice = <const T extends readonly (string | number | boolean)[]>(values: T) => schema<T[number]>({ enum: values }, (v) => values.includes(v as T[number]) ? v as T[number] : invalid());
export const optional = <T>(s: CommandSchema<T>) => schema<T | undefined>(s.jsonSchema, (v) => v === undefined ? undefined : s.parse(v));
export const nullable = <T>(s: CommandSchema<T>) => schema<T | null>({ anyOf: [s.jsonSchema, { type: "null" }] }, (v) => v === null ? null : s.parse(v));
export const array = <T>(s: CommandSchema<T>, maxItems = 512) => schema<T[]>({ type: "array", items: s.jsonSchema, maxItems }, (v) =>
  Array.isArray(v) && v.length <= maxItems ? v.map((item) => s.parse(item)) : invalid());
export function object<const S extends Record<string, CommandSchema<unknown>>>(fields: S): CommandSchema<ObjectParsed<S>> {
  const required = Object.keys(fields).filter((key) => { try { fields[key]!.parse(undefined); return false; } catch { return true; } });
  return schema({ type: "object", properties: Object.fromEntries(Object.entries(fields).map(([k, s]) => [k, s.jsonSchema])), required, additionalProperties: false }, (v) => {
    if (!v || typeof v !== "object" || Array.isArray(v)) invalid();
    const source = v as Record<string, unknown>;
    if (Object.keys(source).some((key) => !Object.hasOwn(fields, key))) invalid("Unknown command argument");
    return Object.fromEntries(Object.entries(fields).map(([key, s]) => [key, s.parse(source[key])]).filter(([, value]) => value !== undefined)) as ObjectParsed<S>;
  });
}
export const empty = object({});
function jsonValue(v: unknown, depth = 0): unknown {
  if (depth > 16) invalid("JSON arguments exceed nesting limit");
  if (v === null || typeof v === "boolean") return v;
  if (typeof v === "number") return number().parse(v);
  if (typeof v === "string") return text(48_000, 0).parse(v);
  if (Array.isArray(v) && v.length <= 2048) return v.map((item) => jsonValue(item, depth + 1));
  if (v && typeof v === "object" && Object.keys(v).length <= 256) {
    if (Object.keys(v).some((key) => ["__proto__", "prototype", "constructor"].includes(key))) invalid();
    return Object.fromEntries(Object.entries(v).map(([key, item]) => [key, jsonValue(item, depth + 1)]));
  }
  return invalid();
}
export const json = schema<unknown>({}, (v) => jsonValue(v));
export const record = schema<Record<string, unknown>>({ type: "object", description: "JSON data validated again by the domain contract; no scripts are evaluated by this adapter." }, (v) => {
  if (!v || typeof v !== "object" || Array.isArray(v)) invalid();
  return jsonValue(v) as Record<string, unknown>;
});
