/** One UTF-8 JSON member in a standard ZIP (stored, bounded input, no dependency). */
export function supportArchive(json: string): Uint8Array<ArrayBuffer> {
  const name = new TextEncoder().encode("diagnostics.json");
  const data = new TextEncoder().encode(json);
  let crc = 0xffffffff;
  for (const byte of data) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
  }
  crc = (crc ^ 0xffffffff) >>> 0;
  const directoryOffset = 30 + name.length + data.length;
  const directorySize = 46 + name.length;
  const bytes = new Uint8Array(directoryOffset + directorySize + 22);
  const view = new DataView(bytes.buffer);
  const u16 = (offset: number, value: number) => view.setUint16(offset, value, true);
  const u32 = (offset: number, value: number) => view.setUint32(offset, value, true);
  u32(0, 0x04034b50); u16(4, 20); u16(6, 0x800); u16(12, 33);
  u32(14, crc); u32(18, data.length); u32(22, data.length); u16(26, name.length);
  bytes.set(name, 30); bytes.set(data, 30 + name.length);
  const c = directoryOffset;
  u32(c, 0x02014b50); u16(c + 4, 20); u16(c + 6, 20); u16(c + 8, 0x800); u16(c + 14, 33);
  u32(c + 16, crc); u32(c + 20, data.length); u32(c + 24, data.length); u16(c + 28, name.length);
  bytes.set(name, c + 46);
  const end = c + directorySize;
  u32(end, 0x06054b50); u16(end + 8, 1); u16(end + 10, 1); u32(end + 12, directorySize); u32(end + 16, c);
  return bytes;
}
