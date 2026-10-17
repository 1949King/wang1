/**
 * dubOrchestration.ts — 多角色配音编排桥（2026-10-15，配音一致性方案 P0⑥）。
 *
 * 为什么另开文件：`bridge.ts` 已逼近单文件规模守卫（2000 行）阈值，按项目纪律
 * 「新桥函数一律另开文件」（照 hostCompliance.ts / hostBreakdownL2.ts / canvasRun.ts 先例）。
 *
 * 解决用户两件痛点：
 *   ① AI 视频模型自带对白「发音与字幕/字对不上」—— 改由**本地 TTS 按角色逐句配音**，
 *      配音音频时长反过来决定镜头时长 ⇒ 音画天然同轴，不再手工排时间线；
 *   ② 多角色配音 + 手工排时间线太费人工 —— 剧本一次解析、逐句路由角色音色、拼成一条轨。
 *
 * 三条端点（后端 canvas_routes_dub.py，真源在后端，这里只接线）：
 *   · POST /host/dub-plan        → dry-run：分句/路由/预估时长，**不合成、不落盘**
 *   · POST /host/dub-execute     → 真跑：逐句合成 → 写 wav → 拼轨 + 反推镜头时长
 *   · POST /host/dub-to-timeline → 配音轨落时间线（后端复用既有唯一入轨 helper，kind="audio"）
 *
 * 诚实降级：查不到角色音色时后端返回 `degraded:true`（用默认声线），这里**如实展示**，
 * 不假装已用上角色专属音色；合成失败逐句回传 `error_message`，不静默丢弃。
 */
import { BRIDGE, bridgeToken } from "./bridge";

export interface DubLine {
  order: number;
  speaker: string | null;
  text: string;
  voice_id?: string | null;
  voice_profile_id?: string;
  route?: string;
  degraded?: boolean;
  degrade_reason?: string;
  estimated_duration?: number;
  duration_source?: string;
}

export interface DubSegment {
  order: number;
  start: number;
  end: number;
  duration: number;
  audio_path: string;
}

export interface DubTrack {
  segments: DubSegment[];
  total: number;
}

export interface DubResultItem {
  order: number;
  speaker: string | null;
  text: string;
  success: boolean;
  is_placeholder?: boolean;
  duration: number;
  audio_path: string;
  error_message?: string;
  degraded?: boolean;
  degrade_reason?: string;
  voice_profile_id?: string;
  route?: string;
}

export interface DubPlanResult {
  ok: boolean;
  lines?: DubLine[];
  track?: DubTrack;
  degraded?: Array<{ order: number; speaker: string | null; reason: string }>;
  note?: string;
  message?: string;
}

export interface DubExecuteResult {
  ok: boolean;
  results?: DubResultItem[];
  track?: DubTrack;
  shots?: Array<Record<string, unknown>>;
  failed?: number;
  degraded?: number;
  /** 是否做了听写回环验证（opt-in）。 */
  verified?: boolean;
  /** 低于阈值的红标句数（>0 需人工复核）。 */
  red_flags?: number;
  /** 来自**音频听写**的字幕段（音→字），非剧本回填。 */
  subtitles?: Array<{ start: number; end: number; text: string; order?: number }>;
  /** "asr" = 字幕来自音频；"unavailable" = ASR 不可用/无音频（如实降级）。 */
  subtitle_source?: string;
  out_dir?: string;
  message?: string;
}

export interface DubToTimelineResult {
  ok: boolean;
  pushed?: number;
  failed?: number;
  items?: Array<{ order: number; audio_path: string }>;
  errors?: Array<{ order: number; audio_path: string; message: string }>;
  message?: string;
}

export interface DubCharacterRef {
  name: string;
  voice_id?: string | null;
  voice_profile_id?: string;
}

export interface DubShotRef {
  id: string;
  dialogue: string;
  duration: number;
}

async function postHost<T>(path: string, payload: Record<string, unknown>): Promise<T> {
  try {
    const res = await fetch(`${BRIDGE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Shiguang-Token": bridgeToken() },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!data || typeof data !== "object") {
      return { ok: false, message: "后端返回非法数据" } as unknown as T;
    }
    return data as T;
  } catch (e) {
    return { ok: false, message: `请求失败: ${e instanceof Error ? e.message : String(e)}` } as unknown as T;
  }
}

/** dry-run：解析剧本 → 逐句角色路由 → 预估时长（不合成、不落盘）。 */
export function dubPlan(
  script: string,
  characters?: DubCharacterRef[],
  gap?: number,
): Promise<DubPlanResult> {
  const payload: Record<string, unknown> = { script };
  if (characters && characters.length) payload.characters = characters;
  if (gap != null) payload.gap = gap;
  return postHost<DubPlanResult>("/host/dub-plan", payload);
}

/** 真跑：逐句 TTS → 写盘 → 拼轨；带 shots 时用配音真实时长反推镜头时长。 */
export function dubExecute(
  script: string,
  opts: {
    characters?: DubCharacterRef[];
    shots?: DubShotRef[];
    gap?: number;
    /** 是否做听写回环验证（会加载 Whisper，较慢；默认关）。 */
    verify?: boolean;
    /** 是否从音频听写字幕（同样加载 Whisper；默认关）。 */
    subtitles?: boolean;
  } = {},
): Promise<DubExecuteResult> {
  const payload: Record<string, unknown> = { script };
  if (opts.characters && opts.characters.length) payload.characters = opts.characters;
  if (opts.shots && opts.shots.length) payload.shots = opts.shots;
  if (opts.gap != null) payload.gap = opts.gap;
  if (opts.verify) payload.verify = true;
  if (opts.subtitles) payload.subtitles = true;
  return postHost<DubExecuteResult>("/host/dub-execute", payload);
}

/** 把已生成的配音段落时间线（后端复用既有唯一入轨通道，kind="audio"）。 */
export function dubToTimeline(segments: DubSegment[]): Promise<DubToTimelineResult> {
  return postHost<DubToTimelineResult>("/host/dub-to-timeline", { segments });
}

/**
 * 从画布节点收集镜头引用（**纯函数**）：只取 kind==="shot" 的节点，
 * 带上 `dialogue`（用于与配音台词匹配）与当前 `duration`（供后端覆盖）。
 */
export function collectShotRefs(
  nodes: ReadonlyArray<{ id: string; data: any }>,
): DubShotRef[] {
  const out: DubShotRef[] = [];
  for (const n of nodes) {
    const d = n?.data || {};
    if (d.kind !== "shot") continue;
    out.push({
      id: String(n.id),
      dialogue: String(d.dialogue || ""),
      duration: Number(d.duration) || 0,
    });
  }
  return out;
}

/**
 * 把后端反推后的镜头时长映射成「节点 id → 补丁」（**纯函数**；前端只负责写回 store）。
 * 只对 `duration_source==="audio"`（真拿到配音音频）的镜头改时长；估算值不动，
 * 避免「没有音频证据却假装已对齐」。
 */
export function buildShotDurationPatches(
  shots: Array<Record<string, unknown>> | undefined,
  refs: DubShotRef[],
): Array<{ id: string; patch: { duration: number; durationSource: string } }> {
  const out: Array<{ id: string; patch: { duration: number; durationSource: string } }> = [];
  const byId = new Map(refs.map((r) => [r.id, r]));
  for (const s of shots || []) {
    const id = String(s.id || "");
    if (!id || !byId.has(id)) continue;
    if (s.duration_source !== "audio") continue; // 无音频证据 ⇒ 保持估算
    out.push({
      id,
      patch: { duration: Number(s.duration) || 0, durationSource: "audio" },
    });
  }
  return out;
}

/** dry-run 计划的可读摘要（**纯函数**，用于确认前展示，便于测试措辞稳定）。 */
export function formatDubPlanForConfirm(plan: DubPlanResult): string {
  const lines = plan.lines || [];
  const track = plan.track;
  const parts: string[] = [
    `配音计划：共 ${lines.length} 句台词`,
    track ? `  预估总时长 ${track.total.toFixed(1)}s（时长以真实配音为准）` : "",
  ].filter(Boolean);
  const named = lines.filter((l) => l.speaker);
  if (named.length) {
    const speakers = Array.from(new Set(named.map((l) => String(l.speaker))));
    parts.push(`  角色 ${speakers.length} 个：${speakers.slice(0, 8).join("、")}${speakers.length > 8 ? "…" : ""}`);
  }
  const deg = plan.degraded || [];
  if (deg.length) {
    parts.push(`  ⚠️ ${deg.length} 句未绑定角色音色，将用默认声线（可在角色库指定音色后重配）`);
  }
  parts.push("", "确认后将逐句合成配音并写入本地（不上云），随后落时间线音轨。");
  return parts.join("\n");
}

/** 执行结果摘要（**纯函数**）。 */
export function summarizeDubExecute(res: DubExecuteResult): string {
  if (!res.ok && !(res.results && res.results.length)) {
    return `配音失败：${res.message || "未知原因"}`;
  }
  const total = res.results?.length || 0;
  const failed = res.failed || 0;
  const secs = res.track ? res.track.total.toFixed(1) : "0";
  const degraded = res.degraded || 0;
  const head = failed === 0
    ? `配音完成：${total - failed}/${total} 句成功，总时长 ${secs}s`
    : `配音部分完成：${total - failed}/${total} 句成功（${failed} 句失败，见各句 error_message）`;
  return degraded > 0 ? `${head}；${degraded} 句使用默认声线` : head;
}
