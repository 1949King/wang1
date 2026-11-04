/**
 * CodeVideoSpec 前端契约镜像（2026-10-20 · V4.46 预备刀）
 *
 * 与后端 `app/core/code_video/spec.py` 同构；**后端 `compile_spec` 是唯一权威**，
 * 本模块只做前端**结构预检 + 常量镜像**，用于：
 *   1. 节点/面板在提交前给出即时错误（少一次往返）；
 *   2. 让「代码 × 扩散」节点与意图胶囊共用同一份类型。
 *
 * 纪律：
 * - 不复制后端语义编译（limits 钳制、lineage 清洗、文字层铁律的最终判定都在后端）；
 * - 常量（SPEC_VERSION / ALLOWED_FPS / TEXT_KINDS / 上限）必须与后端一致，
 *   由 `_verify/check_canvas_capsule_catalog.py` 静态对账；
 * - 零 React/零 store 依赖，可在 node 环境单测。
 */

export const SPEC_VERSION = "1.0";

export const SOURCE_PREFIXES = ["asset://", "html://"] as const;
export const TEXT_KINDS = ["text", "subtitle"] as const;
export const FIT_MODES = ["cover", "contain", "blur-fill"] as const;
export const ALLOWED_FPS = [24, 30] as const;

export const MAX_DURATION = 60;
export const MAX_CLIPS = 12;
export const MAX_CANVAS_W = 1080;
export const MAX_CANVAS_H = 1920;

export type SourcePrefix = (typeof SOURCE_PREFIXES)[number];
export type FitMode = (typeof FIT_MODES)[number];
export type TextKind = (typeof TEXT_KINDS)[number];

export interface CanvasSettings {
  width: number;
  height: number;
  fps: number;
  duration: number;
  background?: string;
}

export interface SpecClip {
  id: string;
  source: string;
  range: [number, number];
  source_range?: [number, number] | null;
  kind: "video" | "text" | "subtitle" | "audio" | "transition";
  fit?: FitMode;
  speed?: number;
  volume?: number;
  params?: Record<string, string | number | boolean | Array<string | number | boolean>>;
  overrides?: Record<string, unknown>;
}

export interface SpecTrack {
  id: string;
  kind: "video" | "subtitle" | "audio";
  clips: SpecClip[];
}

export interface AssetEntry {
  kind: "video" | "image" | "audio";
  duration: number;
  lineage?: Record<string, unknown>;
}

export interface QcSettings {
  dual_shuffle?: boolean;
  text_safe_area?: [number, number, number, number] | null;
}

export interface SpecLineage {
  route: "hybrid" | "diffusion" | "code";
  spec_id: string;
  created_by: string;
}

export interface SpecLimits {
  max_duration: number;
  max_clips: number;
  max_width: number;
  max_height: number;
  allowed_fps: number[];
}

export interface CodeVideoSpecData {
  version: string;
  canvas: CanvasSettings;
  tracks: SpecTrack[];
  assets?: Record<string, AssetEntry>;
  qc?: QcSettings;
  lineage?: SpecLineage;
  limits?: Partial<SpecLimits>;
}

const HTML_NAME_RE = /^[a-z0-9_-]{1,40}\.html$/;
const ASSET_PATH_RE = /^[A-Za-z0-9._\-/]{1,200}$/;

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isRange(value: unknown): value is [number, number] {
  return (
    Array.isArray(value) &&
    value.length === 2 &&
    isFiniteNumber(value[0]) &&
    isFiniteNumber(value[1])
  );
}

/** 结构预检（与后端 `validate_spec` 对齐；不做语义编译）。返回空数组 = 通过。 */
export function validateSpec(data: unknown): string[] {
  const errors: string[] = [];
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    return ["spec 不是对象"];
  }
  const spec = data as Partial<CodeVideoSpecData>;
  if (spec.version !== SPEC_VERSION) {
    errors.push(`version 不支持（只收 ${SPEC_VERSION}，收到 ${String(spec.version)}）`);
  }
  const canvas = spec.canvas;
  if (!canvas || typeof canvas !== "object") {
    errors.push("缺失 canvas 对象");
  } else {
    for (const key of ["width", "height", "fps", "duration"] as const) {
      if (!isFiniteNumber(canvas[key])) errors.push(`canvas.${key} 不是数值`);
    }
  }
  if (!Array.isArray(spec.tracks)) {
    errors.push("缺失 tracks 数组");
  } else {
    const trackIds = new Set<string>();
    const clipIds = new Set<string>();
    spec.tracks.forEach((track, i) => {
      if (!track || typeof track !== "object") {
        errors.push(`tracks[${i}] 不是对象`);
        return;
      }
      if (!track.id) errors.push(`tracks[${i}] 缺失 id`);
      else if (trackIds.has(track.id)) errors.push(`tracks id 重复：${track.id}`);
      else trackIds.add(track.id);
      if (!Array.isArray(track.clips)) {
        errors.push(`tracks[${i}].clips 不是数组`);
        return;
      }
      track.clips.forEach((clip, j) => {
        if (!clip || typeof clip !== "object") {
          errors.push(`tracks[${i}].clips[${j}] 不是对象`);
          return;
        }
        if (!clip.id) errors.push(`tracks[${i}].clips[${j}] 缺失 id`);
        else if (clipIds.has(clip.id)) errors.push(`clip id 重复（跨轨也必须唯一）：${clip.id}`);
        else clipIds.add(clip.id);
        if (!isRange(clip.range)) errors.push(`clips[${j}] (${clip.id || "?"}) range 必须是 [start, end] 两数值`);
        if (typeof clip.source !== "string" || !SOURCE_PREFIXES.some((p) => clip.source.startsWith(p))) {
          errors.push(`clips[${j}] (${clip.id || "?"}) source 必须以 ${SOURCE_PREFIXES.join(" 或 ")} 开头`);
        }
      });
    });
  }
  if (spec.assets !== undefined && (typeof spec.assets !== "object" || Array.isArray(spec.assets))) {
    errors.push("assets 必须是对象（路径 → 登记项）");
  }
  return errors;
}

/** html:// 文件名白名单（与后端一致；供节点输入即时提示）。 */
export function isValidHtmlName(name: string): boolean {
  return HTML_NAME_RE.test(name);
}

/** asset:// 相对路径白名单（与后端一致；防止前端误导用户写绝对路径）。 */
export function isValidAssetPath(path: string): boolean {
  if (!ASSET_PATH_RE.test(path)) return false;
  if (path.startsWith("/") || path.includes("\\")) return false;
  return !path.split("/").includes("..");
}

export function totalClips(spec: CodeVideoSpecData): number {
  return (spec.tracks || []).reduce((sum, track) => sum + (track.clips?.length || 0), 0);
}

export function htmlSources(spec: CodeVideoSpecData): string[] {
  const seen: string[] = [];
  for (const track of spec.tracks || []) {
    for (const clip of track.clips || []) {
      if (clip.source?.startsWith("html://") && !seen.includes(clip.source)) seen.push(clip.source);
    }
  }
  return seen;
}

export function assetKeys(spec: CodeVideoSpecData): string[] {
  return Object.keys(spec.assets || {});
}

/** 文字层铁律的**前端提示**（最终判定仍在后端 compile_spec）。 */
export function textLayerWarnings(spec: CodeVideoSpecData): string[] {
  const warnings: string[] = [];
  for (const track of spec.tracks || []) {
    for (const clip of track.clips || []) {
      if ((TEXT_KINDS as readonly string[]).includes(clip.kind) && !clip.source.startsWith("html://")) {
        warnings.push(`clip ${clip.id}：文字层必须 html://（后端会拒绝渲染）`);
      }
    }
  }
  return warnings;
}

/** 提交给后端的能力参数（spec 原样透传；后端 compile 为唯一权威）。 */
export function toBackendPayload(spec: CodeVideoSpecData): { spec: CodeVideoSpecData } {
  return { spec };
}
