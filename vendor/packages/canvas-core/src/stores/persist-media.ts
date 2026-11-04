/**
 * 工程媒体落盘：把节点里的 dataURL 换成宿主 inbox 引用，避免 localStorage 配额写死。
 */
import type { Node } from "@xyflow/react";
import { persistMediaUrl } from "../bridge";

const DATA_URL_MIN = 4096;

export function collectDataUrls(data: unknown, out: Set<string>, depth = 0): void {
  if (depth > 8 || data == null) return;
  if (typeof data === "string") {
    if (data.startsWith("data:") && data.length >= DATA_URL_MIN) out.add(data);
    return;
  }
  if (Array.isArray(data)) {
    for (const x of data) collectDataUrls(x, out, depth + 1);
    return;
  }
  if (typeof data === "object") {
    for (const v of Object.values(data as Record<string, unknown>)) {
      collectDataUrls(v, out, depth + 1);
    }
  }
}

export function remapMediaUrlInData(data: unknown, from: string, to: string): unknown {
  if (!from || from === to || data == null) return data;
  if (typeof data === "string") return data === from ? to : data;
  if (Array.isArray(data)) {
    let changed = false;
    const next = data.map((x) => {
      const nx = remapMediaUrlInData(x, from, to);
      if (nx !== x) changed = true;
      return nx;
    });
    return changed ? next : data;
  }
  if (typeof data === "object") {
    const obj = data as Record<string, unknown>;
    let changed = false;
    const next: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(obj)) {
      const nv = remapMediaUrlInData(v, from, to);
      next[k] = nv;
      if (nv !== v) changed = true;
    }
    return changed ? next : data;
  }
  return data;
}

export function applyUrlMapToNodes(nodes: Node[], map: Map<string, string>): Node[] {
  let any = false;
  const next = nodes.map((n) => {
    let data: unknown = n.data;
    for (const [from, to] of map) {
      if (from !== to) data = remapMediaUrlInData(data, from, to);
    }
    if (data !== n.data) {
      any = true;
      return { ...n, data: data as Node["data"] };
    }
    return n;
  });
  return any ? next : nodes;
}

export async function persistNodesCopy(nodes: Node[]): Promise<{
  nodes: Node[];
  map: Map<string, string>;
}> {
  const found = new Set<string>();
  for (const n of nodes) collectDataUrls(n.data, found);
  const map = new Map<string, string>();
  for (const u of found) {
    map.set(u, await persistMediaUrl(u));
  }
  return { nodes: applyUrlMapToNodes(nodes, map), map };
}
