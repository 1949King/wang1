/**
 * 画布「神经补帧」桥（T4 项二，2026-11-20）
 * ======================================================
 * 后端真相源：`app/core/video_interpolate_job.py`（run_interpolate）
 *  + 路由 `app/core/canvas_routes_post.py` POST /host/interpolate
 *  + 任务基设 `app/core/canvas_gen_jobs.py`（submit / status）。
 *
 * 单一通道纪律（hostRoughCut.ts 先例）：
 *  - 本文件只做纯函数判读 + fetch 薄封装，不做 UI、不做业务判定。
 *  - `parseInterpolateResult` 是纯函数：vitest 为 node 环境（无 jsdom），
 *    判定逻辑必须放 .ts 才可测。
 *  - **自包含 polling，{ok:false} 契约**：失败返回 {ok:false,error}，**不抛**
 *    （区别于 generationQueue.awaitGeneration 的抛异常契约），让 UI 直接展示。
 *  - 模型缺失时后端返回 guidance（资源地址自取），前端原样透传，绝不自动下载。
 */
import { BRIDGE, authHeaders, bridgeToken } from "./bridge";
import { getGenerationJob, isTerminal, type GenJob } from "./generationQueue";

/** 补帧结果（镜像后端 run_interpolate 返回 dict） */
export type InterpolateResult = {
  ok: boolean;
  error?: string;
  /** 模型缺失引导（资源地址 + 部署步骤），后端诚实返回，前端透传 */
  guidance?: string;
  video_path?: string;
  video_url?: string;
  fps?: number;
  multiplier?: number;
  frames_added?: number;
  /** "rife" | "flow"（flow=降级光流） */
  engine?: string;
  degraded?: boolean;
  reason?: string;
};

function _num(v: unknown, fallback = 0): number {
  if (v == null) return fallback; // null/undefined 视为缺省（Number(null)===0 会误判）
  const n = Number(v);
  return Number.isFinite(n) ? n : fallback;
}

/**
 * 容错解析补帧结果；非对象/缺 ok ⇒ {ok:false}（外部输入面降级展示而非崩）。
 */
export function parseInterpolateResult(raw: unknown): InterpolateResult {
  if (!raw || typeof raw !== "object") return { ok: false, error: "补帧结果为空" };
  const o = raw as Record<string, unknown>;
  if (!o.ok) {
    const res: InterpolateResult = {
      ok: false,
      error: String(o.error ?? o.message ?? "补帧失败"),
    };
    if (o.guidance) res.guidance = String(o.guidance);
    return res;
  }
  const res: InterpolateResult = {
    ok: true,
    video_path: String(o.video_path ?? ""),
    video_url: String(o.video_url ?? ""),
    fps: _num(o.fps),
    multiplier: _num(o.multiplier, 2),
    frames_added: _num(o.frames_added),
    engine: String(o.engine ?? ""),
    degraded: Boolean(o.degraded),
  };
  if (o.reason) res.reason = String(o.reason);
  return res;
}

/** 提交补帧任务，立即返回 job_id。网络/解析失败 {ok:false}，不抛。 */
export async function submitInterpolate(
  payload: Record<string, unknown>,
): Promise<{ ok: boolean; job_id?: string; error?: string }> {
  const token = bridgeToken();
  try {
    const res = await fetch(`${BRIDGE}/host/interpolate?token=${encodeURIComponent(token)}`, {
      method: "POST",
      headers: authHeaders(true),
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!data?.ok) {
      return { ok: false, error: String(data?.message ?? data?.error ?? `提交失败（HTTP ${res.status}）`) };
    }
    return { ok: true, job_id: String(data.job_id ?? "") };
  } catch (e) {
    return { ok: false, error: `补帧请求异常: ${e}` };
  }
}

/** 轮询间隔：先密后疏（镜像 generationQueue.pollDelay）。 */
function pollDelay(elapsedMs: number): number {
  if (elapsedMs < 8_000) return 500;
  if (elapsedMs < 30_000) return 1_000;
  return 2_000;
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const t = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(t);
      resolve();
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

export type InterpolateOptions = {
  onProgress?: (job: GenJob) => void;
  signal?: AbortSignal;
  /** 轮询总超时（毫秒），默认 15 分钟；超时返回 {ok:false}，不自动取消后端 */
  timeoutMs?: number;
};

/**
 * 提交 + 自包含轮询，一步到位。全程 {ok:false} 契约，**不抛**。
 * 取消：signal.abort() → 返回 {ok:false,error:"已取消"}（后端任务可另行 cancel）。
 */
export async function runInterpolate(
  payload: Record<string, unknown>,
  opts: InterpolateOptions = {},
): Promise<InterpolateResult> {
  const { onProgress, signal, timeoutMs = 15 * 60 * 1000 } = opts;
  const sub = await submitInterpolate(payload);
  if (!sub.ok || !sub.job_id) {
    return { ok: false, error: sub.error || "提交补帧任务失败" };
  }
  const t0 = Date.now();
  for (;;) {
    if (signal?.aborted) return { ok: false, error: "已取消" };
    let job: GenJob;
    try {
      job = await getGenerationJob(sub.job_id);
    } catch (e) {
      return { ok: false, error: `查询补帧任务失败: ${e}` };
    }
    onProgress?.(job);
    if (isTerminal(job.status)) {
      if (job.status === "done") return parseInterpolateResult(job.result);
      return {
        ok: false,
        error: job.error || (job.status === "cancelled" ? "已取消" : "补帧失败"),
      };
    }
    if (Date.now() - t0 > timeoutMs) {
      return { ok: false, error: "等待补帧超时，任务仍在后台运行" };
    }
    await sleep(pollDelay(Date.now() - t0), signal);
  }
}
