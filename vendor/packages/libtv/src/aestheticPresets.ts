/**
 * 美学预设包本地管理（审美能力的沉淀与复用）
 *
 * 四维度（用户 2026-10-14 指定）：
 *   1. 提示词风格词库 styleWords  → 拼到分镜 prompt 前缀
 *   2. 镜头语言 camera            → 结构化机位字段（景别/运镜/焦段/光圈/环绕/俯仰）
 *   3. 色调 · LUT tone            → 拼到分镜 prompt 尾巴
 *   4. 节奏 · 音乐风格 rhythm / musicStyle → 拼到分镜 prompt 尾巴
 *
 * 设计对齐 facePresets.ts：版本化 localStorage + normalize 兜底 + JSON 导入导出 + 文件读写。
 * 复用 store 既有 updateNodeData 写入分镜，不改画布冻结区。
 */

const STORAGE_KEY = "shiguang-aesthetic-presets-v1";
const ACTIVE_KEY = "shiguang-aesthetic-active-v1";
const MAX_PRESETS = 60;

/** 镜头语言：与 ShotData 的同名字段对齐，套用时直接写回节点 */
export type AestheticCamera = {
  shotSize?: string;
  movement?: string;
  focalLength?: number;
  aperture?: number;
  cameraYaw?: number;
  cameraPitch?: number;
};

export type AestheticPreset = {
  name: string;
  /** 提示词风格词库（拼到 prompt 前缀） */
  styleWords: string;
  /** 镜头语言 */
  camera: AestheticCamera;
  /** 色调 · LUT */
  tone: string;
  /** 节奏描述 */
  rhythm: string;
  /** 音乐风格 */
  musicStyle: string;
  createdAt: number;
};

const EMPTY_CAMERA: AestheticCamera = {};

function str(v: unknown): string {
  return typeof v === "string" ? v.trim() : "";
}

function num(v: unknown): number | undefined {
  if (typeof v === "number") return Number.isFinite(v) ? v : undefined;
  if (typeof v === "string" && v.trim()) {
    const n = Number(v);
    return Number.isFinite(n) ? n : undefined;
  }
  return undefined;
}

/** 脏字段兜底：任意输入都归一为合法 AestheticPreset，不抛错 */
export function normalizeAestheticPreset(raw: unknown): AestheticPreset {
  const o = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const cam = o.camera && typeof o.camera === "object" ? (o.camera as Record<string, unknown>) : {};
  const camera: AestheticCamera = {
    shotSize: str(cam.shotSize) || undefined,
    movement: str(cam.movement) || undefined,
    focalLength: num(cam.focalLength),
    aperture: num(cam.aperture),
    cameraYaw: num(cam.cameraYaw),
    cameraPitch: num(cam.cameraPitch),
  };
  return {
    name: str(o.name) || "未命名预设",
    styleWords: str(o.styleWords),
    camera,
    tone: str(o.tone),
    rhythm: str(o.rhythm),
    musicStyle: str(o.musicStyle),
    createdAt: Number(o.createdAt) || Date.now(),
  };
}

function readStore(): AestheticPreset[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .filter((p) => p && typeof p === "object")
      .map((p) => normalizeAestheticPreset(p));
  } catch {
    return [];
  }
}

function writeStore(list: AestheticPreset[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(list.slice(0, MAX_PRESETS)));
  } catch {
    // 存储满或禁用 localStorage 时静默失败，不阻塞 UI
  }
}

export function loadAestheticPresets(): AestheticPreset[] {
  return readStore();
}

/** 是否至少有一个维度有效（用于保存前校验） */
export function isPresetUsable(p: AestheticPreset): boolean {
  return Boolean(
    p.styleWords || p.tone || p.rhythm || p.musicStyle || Object.keys(p.camera).length > 0,
  );
}

/** 保存/覆盖同名预设；名字为空或四个维度都空则拒绝 */
export function saveAestheticPreset(preset: AestheticPreset): boolean {
  const name = preset.name.trim();
  if (!name) return false;
  const normalized = normalizeAestheticPreset({ ...preset, name });
  if (!isPresetUsable(normalized)) return false;
  const list = readStore();
  const idx = list.findIndex((p) => p.name === name);
  if (idx >= 0) list[idx] = normalized;
  else list.unshift(normalized);
  writeStore(list);
  return true;
}

export function deleteAestheticPreset(name: string): void {
  writeStore(readStore().filter((p) => p.name !== name));
}

/** 导出单条预设为可下载 JSON 文本 */
export function exportAestheticText(p: AestheticPreset): string {
  return JSON.stringify(
    {
      version: 1,
      exportedAt: new Date().toISOString(),
      name: p.name,
      aesthetic: {
        styleWords: p.styleWords,
        camera: p.camera,
        tone: p.tone,
        rhythm: p.rhythm,
        musicStyle: p.musicStyle,
      },
    },
    null,
    2,
  );
}

export type ImportResult =
  | { ok: true; preset: AestheticPreset }
  | { ok: false; error: string };

/** 导入文本：支持两种格式
 *  1. 本模块导出的 { version, name, aesthetic: {...} }
 *  2. 纯预设对象（任意字段，过 normalize 兜底）
 */
export function importAestheticText(text: string): ImportResult {
  const trimmed = text.trim();
  if (!trimmed) return { ok: false, error: "空内容" };
  try {
    const parsed = JSON.parse(trimmed);
    const raw = parsed && typeof parsed === "object" ? (parsed.aesthetic ?? parsed) : parsed;
    if (!raw || typeof raw !== "object") return { ok: false, error: "不是有效的 JSON 对象" };
    const name =
      typeof parsed.name === "string" && parsed.name.trim()
        ? parsed.name.trim()
        : `导入预设 ${new Date().toLocaleTimeString()}`;
    return { ok: true, preset: normalizeAestheticPreset({ ...(raw as object), name }) };
  } catch (e) {
    return { ok: false, error: `JSON 解析失败: ${e instanceof Error ? e.message : String(e)}` };
  }
}

/** 触发浏览器下载 JSON 文件 */
export function downloadAestheticFile(p: AestheticPreset): void {
  if (typeof window === "undefined") return;
  const blob = new Blob([exportAestheticText(p)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `aesthetic-preset-${p.name.replace(/[^\w\u4e00-\u9fa5\-]/g, "_")}.json`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

/** 从 File 对象读文本 */
export function readAestheticFile(file: File): Promise<ImportResult> {
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onload = () => resolve(importAestheticText(String(reader.result ?? "")));
    reader.onerror = () => resolve({ ok: false, error: "文件读取失败" });
    reader.readAsText(file);
  });
}

/**
 * 把预设四维度套到一条分镜 prompt。
 * 幂等：已包含的片段不重复追加（重复套用同一预设不会把 prompt 撑炸）。
 */
export function composeAestheticPrompt(existing: string, preset: AestheticPreset): string {
  const core = (existing || "").trim();
  const head = preset.styleWords.trim();
  const tail = [preset.tone, preset.rhythm, preset.musicStyle]
    .map((s) => s.trim())
    .filter(Boolean);
  const out: string[] = [];
  if (head && !core.includes(head)) out.push(head);
  if (core) out.push(core);
  for (const t of tail) if (!core.includes(t)) out.push(t);
  return out.join("，");
}

/**
 * 生成 updateNodeData 用的补丁：prompt（风格/色调/节奏/音乐）+ 镜头语言字段。
 * 未设置的维度不写入，避免覆盖节点既有值。
 */
export function buildAestheticPatch(
  existingPrompt: string,
  preset: AestheticPreset,
): Record<string, unknown> {
  const patch: Record<string, unknown> = {
    prompt: composeAestheticPrompt(existingPrompt, preset),
  };
  const cam = preset.camera || EMPTY_CAMERA;
  if (cam.shotSize) patch.shotSize = cam.shotSize;
  if (cam.movement) patch.movement = cam.movement;
  if (cam.focalLength !== undefined) patch.focalLength = cam.focalLength;
  if (cam.aperture !== undefined) patch.aperture = cam.aperture;
  if (cam.cameraYaw !== undefined) patch.cameraYaw = cam.cameraYaw;
  if (cam.cameraPitch !== undefined) patch.cameraPitch = cam.cameraPitch;
  return patch;
}

/** —— 生成时自动注入：当前激活的美学预设 —— */

/** 当前激活预设名（空 = 不自动注入） */
export function getActiveAestheticName(): string {
  if (typeof window === "undefined") return "";
  try {
    return window.localStorage.getItem(ACTIVE_KEY) || "";
  } catch {
    return "";
  }
}

/** 设置 / 取消当前激活预设（null 取消） */
export function setActiveAestheticPreset(name: string | null): void {
  if (typeof window === "undefined") return;
  try {
    if (name) window.localStorage.setItem(ACTIVE_KEY, name);
    else window.localStorage.removeItem(ACTIVE_KEY);
  } catch {
    // 禁用 localStorage 时静默失败
  }
}

/** 读回当前激活预设对象（预设已被删除时返回 null，避免注入脏值） */
export function getActiveAestheticPreset(): AestheticPreset | null {
  const name = getActiveAestheticName();
  if (!name) return null;
  return readStore().find((p) => p.name === name) || null;
}

/** 把当前激活预设的提示词文本维度（风格 / 色调 / 节奏 / 音乐）叠到生成提示词；无激活则原样返回。 */
export function applyActiveAestheticToPrompt(prompt: string): string {
  const preset = getActiveAestheticPreset();
  if (!preset) return prompt;
  return composeAestheticPrompt(prompt, preset);
}
