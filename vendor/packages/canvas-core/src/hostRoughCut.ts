/**
 * 画布「粗剪审核卡」桥（§6.9-P2 画布消费接线，2026-10-17）
 * ======================================================
 * 后端真相源：`app/core/rough_cut_chain.py`
 *  - `_broadcast()` 双通道广播：Qt EventBus（剪辑侧栏）+ push_to_canvas
 *    （SSE 事件 type=`rough_cut.review`，payload.subtype 区分阶段）。
 *  - 回写端点：`app/core/canvas_routes_roughcut.py`
 *    （POST /host/rough-cut/apply|export）。
 *
 * 单一通道纪律（hostCompliance.ts / dubOrchestration.ts 先例）：
 *  - 本文件**只做纯函数判读 + fetch 薄封装**，不做 UI、不做业务判定。
 *  - `parseRoughCutEvent` 是纯函数：vitest 为 node 环境（无 jsdom），
 *    判定逻辑必须放 .ts 才可测，React 组件不可测。
 *  - **confirmed=True 由后端端点钉死**：前端不传 confirmed 参数，
 *    「确认后执行」闸门不可被前端绕过。
 *  - fetch 失败**不抛**，返回 {ok:false, error/message}，让 UI 直接展示。
 */
import { BRIDGE, authHeaders, bridgeToken } from "./bridge";
import type { AgentEventEnvelope } from "./agentEvents";

/** 一条待删区间（镜像后端 proposal.intervals 行，rough_cut_chain.py L219） */
export type RoughCutInterval = {
  clip_id: string;
  track: number;
  timeline_in: number;
  timeline_out: number;
  /** filler=水词 / silence=长静音（以后端 kind 为准，前端不复制判定规则） */
  kind: string;
  text: string;
};

/** 提案汇总（镜像后端 summary dict） */
export type RoughCutSummary = {
  original_duration: number;
  predicted_duration: number;
  deleted_duration: number;
  interval_count: number;
};

export type RoughCutPlanReady = {
  subtype: "rough_cut_plan_ready";
  plan_id: string;
  request_id: string;
  summary: RoughCutSummary;
  intervals: RoughCutInterval[];
  warnings: string[];
  message: string;
};

export type RoughCutApplied = {
  subtype: "rough_cut_applied";
  plan_id: string;
  request_id: string;
  deleted_count: number;
  final_duration: number;
  message: string;
};

export type RoughCutEvent = RoughCutPlanReady | RoughCutApplied;

function _num(v: unknown, fallback = 0): number {
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

/** 容错解析一条待删区间；缺关键字段的条目丢弃（不猜、不留脏行） */
function _parseInterval(raw: unknown): RoughCutInterval | null {
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  const clipId = String(o.clip_id ?? "");
  if (!clipId) return null;
  return {
    clip_id: clipId,
    track: _num(o.track),
    timeline_in: _num(o.timeline_in),
    timeline_out: _num(o.timeline_out),
    kind: String(o.kind ?? ""),
    text: String(o.text ?? ""),
  };
}

/**
 * 把一条 SSE 信封判读成粗剪事件；非粗剪事件返回 null（调用方直接丢弃）。
 *
 * 只认 `type === "rough_cut.review"`；payload 字段一律做类型防御 ——
 * SSE 是外部输入面，后端结构演进时前端**降级展示**而不是崩。
 */
export function parseRoughCutEvent(env: AgentEventEnvelope): RoughCutEvent | null {
  if (!env || env.type !== "rough_cut.review") return null;
  const p = env.payload;
  if (!p || typeof p !== "object") return null;
  const subtype = String((p as Record<string, unknown>).subtype ?? "");
  const planId = String((p as Record<string, unknown>).plan_id ?? "");
  if (!planId) return null;
  const requestId = String((p as Record<string, unknown>).request_id ?? "");

  if (subtype === "rough_cut_plan_ready") {
    const s = ((p as Record<string, unknown>).summary ?? {}) as Record<string, unknown>;
    const rawIntervals = (p as Record<string, unknown>).intervals;
    const intervals = Array.isArray(rawIntervals)
      ? (rawIntervals.map(_parseInterval).filter(Boolean) as RoughCutInterval[])
      : [];
    const rawWarnings = (p as Record<string, unknown>).warnings;
    return {
      subtype: "rough_cut_plan_ready",
      plan_id: planId,
      request_id: requestId,
      summary: {
        original_duration: _num(s.original_duration),
        predicted_duration: _num(s.predicted_duration),
        deleted_duration: _num(s.deleted_duration),
        interval_count: _num(s.interval_count, intervals.length),
      },
      intervals,
      warnings: Array.isArray(rawWarnings) ? rawWarnings.map((w) => String(w)) : [],
      message: String((p as Record<string, unknown>).message ?? "粗剪提案已生成，请审核后确认执行"),
    };
  }

  if (subtype === "rough_cut_applied") {
    return {
      subtype: "rough_cut_applied",
      plan_id: planId,
      request_id: requestId,
      deleted_count: _num((p as Record<string, unknown>).deleted_count),
      final_duration: _num((p as Record<string, unknown>).final_duration),
      message: String((p as Record<string, unknown>).message ?? "粗剪已写回"),
    };
  }

  return null;
}

/** apply 端点返回（镜像 canvas_routes_roughcut.py 的透传 dict） */
export type RoughCutApplyResult = {
  ok: boolean;
  message?: string;
  error?: string;
  plan_id?: string;
  deleted_count?: number;
  final_duration?: number;
};

/** export 端点返回（final_video_path 与 pipeline 出片同口径） */
export type RoughCutExportResult = {
  ok: boolean;
  error?: string;
  final_video_path?: string;
  output_path?: string;
};

/**
 * 确认执行：POST /host/rough-cut/apply。
 * 不传 confirmed —— 后端端点钉死 confirmed=True（人工确认时刻=点这个按钮）。
 * 网络/解析失败返回 {ok:false}，**不抛**。
 */
export async function applyRoughCutPlan(planId: string): Promise<RoughCutApplyResult> {
  const token = bridgeToken();
  try {
    const res = await fetch(`${BRIDGE}/host/rough-cut/apply?token=${encodeURIComponent(token)}`, {
      method: "POST",
      headers: authHeaders(true),
      body: JSON.stringify({ plan_id: planId }),
    });
    return (await res.json()) as RoughCutApplyResult;
  } catch (e) {
    return { ok: false, error: `粗剪写回请求异常: ${e}` };
  }
}

/**
 * 导出成片：POST /host/rough-cut/export（后端在 HTTP 线程长渲染，无超时上限；
 * 未先 apply 会被后端拒绝 —— 顺序纪律由后端把关，前端只透传错误）。
 */
export async function exportRoughCutPlan(
  planId: string,
  sessionId = "",
): Promise<RoughCutExportResult> {
  const token = bridgeToken();
  try {
    const res = await fetch(`${BRIDGE}/host/rough-cut/export?token=${encodeURIComponent(token)}`, {
      method: "POST",
      headers: authHeaders(true),
      body: JSON.stringify({ plan_id: planId, session_id: sessionId }),
    });
    return (await res.json()) as RoughCutExportResult;
  } catch (e) {
    return { ok: false, error: `粗剪导出请求异常: ${e}` };
  }
}
