import { createHash, randomBytes } from "node:crypto";

const CHUNK = 32 * 1024;
const MAX_FILE = 32 * 1024 * 1024;
const MAX_TOTAL = 128 * 1024 * 1024;
const fail = (code) => { throw Object.assign(new Error(code), { code }); };
/** Process-local, window-bound bytes. No host paths, automatic downloads or persistent credentials. */
export class ControlFiles {
  constructor({ now = Date.now } = {}) { this.entries = new Map(); this.now = now; }
  clear(windowId) { for (const [id, entry] of this.entries) if (!windowId || entry.windowId === windowId) this.entries.delete(id); }
  call(windowId, operation, input, edit) {
    if (!input || typeof input !== "object" || Array.isArray(input)) fail("INVALID_PARAMS");
    for (const [id, entry] of this.entries) if (this.now() - entry.touched > 30 * 60 * 1000) this.entries.delete(id);
    const keys = { begin: ["uploadId", "name", "mimeType", "size", "sha256"], write: ["fileRef", "offset", "data"], commit: ["fileRef"], read: ["fileRef", "offset"], remove: ["fileRef"] };
    if (!Object.hasOwn(keys, operation) || Object.keys(input).some((key) => !keys[operation].includes(key))) fail("INVALID_PARAMS");
    if (operation !== "read" && !edit) fail("SCOPE_DENIED");
    if (operation === "begin") {
      const { uploadId, name, mimeType, size, sha256 } = input;
      if (typeof uploadId !== "string" || !/^[A-Za-z0-9._:-]{1,96}$/.test(uploadId)
        || typeof name !== "string" || !name.length || name.length > 160 || /[\\/]/.test(name) || [...name].some((char) => char.charCodeAt(0) < 32) || name === "." || name === ".."
        || typeof mimeType !== "string" || mimeType.length > 128 || /[\r\n]/.test(mimeType)
        || !Number.isSafeInteger(size) || size < 0 || size > MAX_FILE || !/^[a-f0-9]{64}$/.test(sha256 ?? "")) fail("INVALID_PARAMS");
      const fingerprint = JSON.stringify(input);
      const prior = [...this.entries.values()].find((entry) => entry.windowId === windowId && entry.uploadId === uploadId);
      if (prior) { if (prior.fingerprint !== fingerprint) fail("UPLOAD_ID_CONFLICT"); return this.metadata(prior); }
      if (this.entries.size >= 64 || [...this.entries.values()].reduce((n, e) => n + e.size, size) > MAX_TOTAL) fail("FILE_BUDGET");
      const fileRef = randomBytes(24).toString("hex");
      const entry = { ...input, fileRef, windowId, fingerprint, bytes: Buffer.alloc(size), offset: 0, committed: false, touched: this.now() };
      this.entries.set(fileRef, entry); return this.metadata(entry);
    }
    const entry = this.entries.get(input.fileRef);
    if (!entry || entry.windowId !== windowId) fail("FILE_UNAVAILABLE");
    entry.touched = this.now();
    if (operation === "remove") { this.entries.delete(entry.fileRef); return { removed: true }; }
    if (operation === "write") {
      if (typeof input.data !== "string" || input.data.length > Math.ceil(CHUNK / 3) * 4 || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(input.data)) fail("INVALID_PARAMS");
      const bytes = Buffer.from(input.data, "base64");
      if (!Number.isSafeInteger(input.offset) || input.offset < 0 || bytes.length === 0 || bytes.length > CHUNK || input.offset + bytes.length > entry.size) fail("INVALID_PARAMS");
      if (input.offset < entry.offset && input.offset + bytes.length <= entry.offset && entry.bytes.subarray(input.offset, input.offset + bytes.length).equals(bytes)) return this.metadata(entry);
      if (entry.committed || input.offset !== entry.offset) fail("FILE_OFFSET_CONFLICT");
      bytes.copy(entry.bytes, entry.offset); entry.offset += bytes.length; return this.metadata(entry);
    }
    if (operation === "commit") {
      if (entry.offset !== entry.size) fail("FILE_INCOMPLETE");
      if (createHash("sha256").update(entry.bytes).digest("hex") !== entry.sha256) fail("FILE_HASH_MISMATCH");
      entry.committed = true; return this.metadata(entry);
    }
    if (!entry.committed) fail("FILE_INCOMPLETE");
    if (!Number.isSafeInteger(input.offset) || input.offset < 0 || input.offset > entry.size) fail("INVALID_PARAMS");
    return { ...this.metadata(entry), data: entry.bytes.subarray(input.offset, input.offset + CHUNK).toString("base64") };
  }
  metadata({ fileRef, name, mimeType, size, sha256, offset, committed }) { return { fileRef, name, mimeType, size, sha256, offset, committed, chunkBytes: CHUNK }; }
}
