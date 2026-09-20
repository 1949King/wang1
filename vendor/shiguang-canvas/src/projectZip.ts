/** 工程 ZIP（STORE 无压缩）导入导出 — 对齐 infinite-canvas 换机带走能力 */

import type { Edge, Node } from "@xyflow/react";

export type ProjectBundle = {
  version?: number;
  schemaVersion?: number;
  dramaTitle: string;
  episode: string;
  nodes: Node[];
  edges: Edge[];
  savedAt: string;
  /** 3D 导演台场景快照 */
  stage3d?: unknown;
  /** 工程级快照（P1-4）：剪辑器时间线（完整 _clips，可回滚/diff/直导） */
  timeline?: {
    clips: unknown[];
    clip_count?: number;
    taken_at?: string;
  };
};

function crc32(buf: Uint8Array): number {
  let c = ~0;
  for (let i = 0; i < buf.length; i++) {
    c ^= buf[i];
    for (let k = 0; k < 8; k++) c = c & 1 ? (c >>> 1) ^ 0xedb88320 : c >>> 1;
  }
  return ~c >>> 0;
}

function u16(n: number) {
  const b = new Uint8Array(2);
  new DataView(b.buffer).setUint16(0, n, true);
  return b;
}

function u32(n: number) {
  const b = new Uint8Array(4);
  new DataView(b.buffer).setUint32(0, n, true);
  return b;
}

function concat(parts: Uint8Array[]) {
  const len = parts.reduce((a, p) => a + p.length, 0);
  const out = new Uint8Array(len);
  let o = 0;
  for (const p of parts) {
    out.set(p, o);
    o += p.length;
  }
  return out;
}

function encodeUtf8(s: string) {
  return new TextEncoder().encode(s);
}

/** 写仅 STORE 方法的单文件 ZIP */
export function buildZip(files: { name: string; data: Uint8Array }[]): Blob {
  const localParts: Uint8Array[] = [];
  const centralParts: Uint8Array[] = [];
  let offset = 0;
  for (const f of files) {
    const nameBytes = encodeUtf8(f.name);
    const crc = crc32(f.data);
    const local = concat([
      u32(0x04034b50),
      u16(20),
      u16(0),
      u16(0),
      u16(0),
      u16(0),
      u32(crc),
      u32(f.data.length),
      u32(f.data.length),
      u16(nameBytes.length),
      u16(0),
      nameBytes,
      f.data,
    ]);
    localParts.push(local);
    const central = concat([
      u32(0x02014b50),
      u16(20),
      u16(20),
      u16(0),
      u16(0),
      u16(0),
      u16(0),
      u32(crc),
      u32(f.data.length),
      u32(f.data.length),
      u16(nameBytes.length),
      u16(0),
      u16(0),
      u16(0),
      u16(0),
      u32(0),
      u32(offset),
      nameBytes,
    ]);
    centralParts.push(central);
    offset += local.length;
  }
  const centralDir = concat(centralParts);
  const end = concat([
    u32(0x06054b50),
    u16(0),
    u16(0),
    u16(files.length),
    u16(files.length),
    u32(centralDir.length),
    u32(offset),
    u16(0),
  ]);
  return new Blob([concat([...localParts, centralDir, end])], { type: "application/zip" });
}

function findZipEntries(buf: Uint8Array): { name: string; data: Uint8Array }[] {
  const view = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  const out: { name: string; data: Uint8Array }[] = [];
  let i = 0;
  while (i + 30 < buf.length) {
    if (view.getUint32(i, true) !== 0x04034b50) break;
    const method = view.getUint16(i + 8, true);
    const compSize = view.getUint32(i + 18, true);
    const nameLen = view.getUint16(i + 26, true);
    const extraLen = view.getUint16(i + 28, true);
    const name = new TextDecoder().decode(buf.subarray(i + 30, i + 30 + nameLen));
    const dataStart = i + 30 + nameLen + extraLen;
    const data = buf.subarray(dataStart, dataStart + compSize);
    if (method !== 0) {
      throw new Error(`ZIP 条目「${name}」使用了压缩方法 ${method}，仅支持 STORE`);
    }
    out.push({ name, data: new Uint8Array(data) });
    i = dataStart + compSize;
  }
  return out;
}

function dataUrlToBytes(dataUrl: string): { ext: string; bytes: Uint8Array } | null {
  const m = /^data:([^;,]+)?(;base64)?,(.*)$/s.exec(dataUrl);
  if (!m) return null;
  const mime = m[1] || "application/octet-stream";
  const isB64 = Boolean(m[2]);
  const payload = m[3] || "";
  let bytes: Uint8Array;
  if (isB64) {
    const bin = atob(payload);
    bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  } else {
    bytes = encodeUtf8(decodeURIComponent(payload));
  }
  const ext =
    mime.includes("png") ? "png" : mime.includes("jpeg") || mime.includes("jpg") ? "jpg" : mime.includes("webp")
      ? "webp"
      : mime.includes("mp4")
        ? "mp4"
        : mime.includes("audio") || mime.includes("mpeg") || mime.includes("wav")
          ? "bin"
          : "bin";
  return { ext, bytes };
}

function bytesToDataUrl(bytes: Uint8Array, mime: string) {
  let s = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    s += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return `data:${mime};base64,${btoa(s)}`;
}

/** 导出工程：project.json + media/* */
export async function exportProjectZip(bundle: ProjectBundle): Promise<Blob> {
  const mediaMap: Record<string, string> = {};
  let mediaIdx = 0;
  const rewriteUrl = (url?: string) => {
    if (!url || !url.startsWith("data:")) return url;
    const parsed = dataUrlToBytes(url);
    if (!parsed) return url;
    const key = `media/m${mediaIdx++}.${parsed.ext}`;
    mediaMap[key] = url;
    return `zip://${key}`;
  };
  const nodes = JSON.parse(JSON.stringify(bundle.nodes)) as Node[];
  for (const n of nodes) {
    const d = n.data as Record<string, unknown>;
    for (const k of [
      "imageUrl",
      "firstFrameUrl",
      "lastFrameUrl",
      "posterUrl",
      "videoUrl",
      "audioUrl",
      "refVideoUrl",
    ]) {
      if (typeof d[k] === "string") d[k] = rewriteUrl(d[k] as string);
    }
    if (Array.isArray(d.images)) {
      d.images = (d.images as { id: string; url: string }[]).map((im) => ({
        ...im,
        url: rewriteUrl(im.url) || im.url,
      }));
    }
  }
  const project: ProjectBundle = {
    ...bundle,
    nodes,
    savedAt: new Date().toISOString(),
  };
  const files: { name: string; data: Uint8Array }[] = [
    { name: "project.json", data: encodeUtf8(JSON.stringify(project, null, 2)) },
  ];
  for (const [path, dataUrl] of Object.entries(mediaMap)) {
    const parsed = dataUrlToBytes(dataUrl);
    if (parsed) files.push({ name: path, data: parsed.bytes });
  }
  return buildZip(files);
}

export async function importProjectZip(file: File | Blob): Promise<ProjectBundle> {
  const buf = new Uint8Array(await file.arrayBuffer());
  const entries = findZipEntries(buf);
  const byName = new Map(entries.map((e) => [e.name, e.data]));
  const raw = byName.get("project.json");
  if (!raw) throw new Error("ZIP 内缺少 project.json");
  const project = JSON.parse(new TextDecoder().decode(raw)) as ProjectBundle;
  const resolve = (url?: string) => {
    if (!url || !url.startsWith("zip://")) return url;
    const path = url.slice("zip://".length);
    const bytes = byName.get(path);
    if (!bytes) return url;
    const ext = path.split(".").pop() || "bin";
    const mime =
      ext === "png"
        ? "image/png"
        : ext === "jpg" || ext === "jpeg"
          ? "image/jpeg"
          : ext === "webp"
            ? "image/webp"
            : ext === "mp4"
              ? "video/mp4"
              : "application/octet-stream";
    return bytesToDataUrl(bytes, mime);
  };
  for (const n of project.nodes || []) {
    const d = n.data as Record<string, unknown>;
    for (const k of [
      "imageUrl",
      "firstFrameUrl",
      "lastFrameUrl",
      "posterUrl",
      "videoUrl",
      "audioUrl",
      "refVideoUrl",
    ]) {
      if (typeof d[k] === "string") d[k] = resolve(d[k] as string);
    }
    if (Array.isArray(d.images)) {
      d.images = (d.images as { id: string; url: string }[]).map((im) => ({
        ...im,
        url: resolve(im.url) || im.url,
      }));
    }
  }
  return project;
}

// ── 工程级快照（P1-4）：时间线抓取 / diff / 直导 ──────────────────

import { bridgeToken } from "./bridge";

export type TimelineClipRow = Record<string, unknown>;
export type TimelinePayload = { clips: TimelineClipRow[]; clip_count?: number; taken_at?: string };

/** 从桥抓取剪辑器完整时间线（走 /host/project-snapshot/export）。失败返回 null，不抛。 */
export async function fetchProjectTimeline(): Promise<TimelinePayload | null> {
  try {
    const res = await fetch(
      `${location.origin}/host/project-snapshot/export?token=${encodeURIComponent(bridgeToken())}`,
      { headers: { "X-Shiguang-Token": bridgeToken() } },
    );
    const data = await res.json();
    if (!data?.ok) return null;
    const timeline = data.timeline || {};
    return {
      clips: Array.isArray(timeline.clips) ? timeline.clips : [],
      clip_count: timeline.clip_count,
      taken_at: timeline.taken_at,
    };
  } catch {
    return null;
  }
}

/** 把时间线写回剪辑器（直导）。返回 {ok, message}。 */
export async function pushTimelineToEditor(clips: TimelineClipRow[]): Promise<{ ok: boolean; message: string }> {
  try {
    const res = await fetch(
      `${location.origin}/host/project-snapshot/import?token=${encodeURIComponent(bridgeToken())}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Shiguang-Token": bridgeToken() },
        body: JSON.stringify({ clips }),
      },
    );
    return await res.json();
  } catch (e) {
    return { ok: false, message: `直导剪辑器失败: ${e}` };
  }
}

/** 结构 diff 两份时间线（纯前端，供「导入前预览差异」展示）。 */
export function diffTimelineClips(
  before: TimelineClipRow[],
  after: TimelineClipRow[],
): { added: number; removed: number; changed: { clip_id: unknown; field: string }[] } {
  const key = (c: TimelineClipRow) => c.id ?? `${c.path}@${c.start_time}`;
  const bm = new Map(before.map((c) => [key(c), c]));
  const am = new Map(after.map((c) => [key(c), c]));
  const added = [...am.keys()].filter((k) => !bm.has(k)).length;
  const removed = [...bm.keys()].filter((k) => !am.has(k)).length;
  const changed: { clip_id: unknown; field: string }[] = [];
  for (const [k, bc] of bm) {
    const ac = am.get(k);
    if (!ac) continue;
    for (const f of ["start_time", "duration", "in_point", "out_point", "path", "name"]) {
      if (bc[f] !== ac[f]) changed.push({ clip_id: bc.id, field: f });
    }
  }
  return { added, removed, changed };
}

export function downloadBlob(blob: Blob, filename: string) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}
