/**
 * 捏脸预设本地管理（C + D：保存/加载/导入/导出）
 *
 * 设计：
 *  - 只存序列化后的 faceParams JSON 串 + 元数据，不存对象引用；
 *  - 读回时统一过 `normalizeFaceParams` 兜底，旧版本/脏字段不崩；
 *  - 导出为可下载 .json，导入接受文件或剪贴板文本；
 *  - localStorage key 带版本号，未来可迁移。
 */
import { normalizeFaceParams, serializeFaceParams, type FaceParams } from "./faceParams";

const STORAGE_KEY = "shiguang-face-presets-v1";
const MAX_PRESETS = 50;

export type FacePreset = {
  name: string;
  /** 序列化后的 faceParams JSON */
  serialized: string;
  createdAt: number;
};

function readStore(): FacePreset[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((p) => p && typeof p.name === "string" && typeof p.serialized === "string")
      .map((p) => ({ name: p.name, serialized: p.serialized, createdAt: Number(p.createdAt) || Date.now() }));
  } catch {
    return [];
  }
}

function writeStore(list: FacePreset[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(list.slice(0, MAX_PRESETS)));
  } catch {
    // 存储满或禁用 localStorage 时静默失败，不阻塞 UI
  }
}

export function loadFacePresets(): FacePreset[] {
  return readStore();
}

/** 保存/覆盖同名预设 */
export function saveFacePreset(name: string, params: FaceParams): boolean {
  const list = readStore();
  const serialized = serializeFaceParams(params);
  const idx = list.findIndex((p) => p.name === name);
  const entry: FacePreset = { name, serialized, createdAt: Date.now() };
  if (idx >= 0) list[idx] = entry;
  else list.unshift(entry);
  writeStore(list);
  return true;
}

export function deleteFacePreset(name: string): void {
  const list = readStore().filter((p) => p.name !== name);
  writeStore(list);
}

export function loadPresetParams(p: FacePreset): FaceParams {
  return normalizeFaceParams(p.serialized);
}

/** 导出单条预设为可下载 JSON 文本 */
export function exportPresetText(p: FacePreset): string {
  return JSON.stringify(
    {
      version: 1,
      exportedAt: new Date().toISOString(),
      name: p.name,
      faceParams: JSON.parse(p.serialized),
    },
    null,
    2,
  );
}

export type ImportResult =
  | { ok: true; name: string; params: FaceParams }
  | { ok: false; error: string };

/** 导入文本：支持两种格式
 *  1. 本模块导出的 { version, name, faceParams: {...} }
 *  2. 纯 faceParams 对象（任意字段，过 normalize 兜底）
 */
export function importPresetText(text: string): ImportResult {
  const trimmed = text.trim();
  if (!trimmed) return { ok: false, error: "空内容" };
  try {
    const parsed = JSON.parse(trimmed);
    const raw = parsed && typeof parsed === "object" ? (parsed.faceParams ?? parsed) : parsed;
    if (!raw || typeof raw !== "object") return { ok: false, error: "不是有效的 JSON 对象" };
    const params = normalizeFaceParams(raw);
    const name = typeof parsed.name === "string" && parsed.name.trim()
      ? parsed.name.trim()
      : `导入预设 ${new Date().toLocaleTimeString()}`;
    return { ok: true, name, params };
  } catch (e) {
    return { ok: false, error: `JSON 解析失败: ${e instanceof Error ? e.message : String(e)}` };
  }
}

/** 触发浏览器下载 JSON 文件 */
export function downloadPresetFile(p: FacePreset): void {
  if (typeof window === "undefined") return;
  const blob = new Blob([exportPresetText(p)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `face-preset-${p.name.replace(/[^\w\u4e00-\u9fa5\-]/g, "_")}.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/** 从 File 对象读文本 */
export function readPresetFile(file: File): Promise<ImportResult> {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve(importPresetText(String(reader.result ?? "")));
    reader.onerror = () => resolve({ ok: false, error: "文件读取失败" });
    reader.readAsText(file);
  });
}
