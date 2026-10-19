import assert from "node:assert/strict";
import test from "node:test";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import os from "node:os";
import { ControlFiles } from "../../frontend/desktop/control-files.mjs";
import { uploadFile, downloadFile } from "./files.mjs";

test("CLI file helpers transfer multiple chunks, verify identity and refuse to overwrite a destination", async (t) => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "candlescope-files-"));
  t.after(async () => { assert.ok(directory.startsWith(path.join(os.tmpdir(), "candlescope-files-"))); await rm(directory, { recursive: true, force: true }); });
  const store = new ControlFiles();
  const client = { call: async (method, { windowId, ...input }) => store.call(windowId, method.slice(5), input, true) };
  const source = path.join(directory, "candles.csv"), destination = path.join(directory, "download.csv");
  const bytes = Buffer.from("time,open,high,low,close\n".repeat(4096)); await writeFile(source, bytes);
  const file = await uploadFile(client, "w", source); assert.equal(file.name, "candles.csv"); assert.equal(file.committed, true);
  await downloadFile(client, "w", file.fileRef, destination); assert.deepEqual(await readFile(destination), bytes);
  await assert.rejects(downloadFile(client, "w", file.fileRef, destination), { code: "EEXIST" }); assert.deepEqual(await readFile(destination), bytes);
  await assert.rejects(downloadFile(client, "other", file.fileRef, path.join(directory, "wrong.csv")), /FILE_UNAVAILABLE/);
});
test("download hash failures never create the output file", async (t) => {
  const directory = await mkdtemp(path.join(os.tmpdir(), "candlescope-files-"));
  t.after(async () => { assert.ok(directory.startsWith(path.join(os.tmpdir(), "candlescope-files-"))); await rm(directory, { recursive: true, force: true }); });
  const output = path.join(directory, "invalid.json");
  const client = { call: async () => ({ committed: true, size: 2, data: Buffer.from("{}").toString("base64"), sha256: "0".repeat(64) }) };
  await assert.rejects(downloadFile(client, "w", "ref", output), /FILE_HASH_MISMATCH/);
  await assert.rejects(readFile(output), { code: "ENOENT" });
});
