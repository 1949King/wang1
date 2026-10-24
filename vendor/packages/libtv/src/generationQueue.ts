/**
 * generationQueue — 画布生成任务的前端编排层
 *
 * 为什么单独建文件（而不改 bridge.ts）：
 *   1. `bridge.ts` 在双库（shiguang-canvas / AI-Canvas-tauri）之间已处于「已分叉」状态，
 *      不再往里堆新逻辑，避免漂移继续扩大；
 *   2. `CanvasShell.tsx` / `store.ts` / `mediaExtraNodes.tsx` 等属冻结区，新能力放这儿零风险。
 *
 * 三件事：
 *   A. **异步任务化**：submit → 轮询 status → 终态取结果。主生成路径不再阻塞。
 *   B. **真实进度**：后端 `progress` 为 null 时只渲染「阶段 + 已用时」，
 *      **不伪造百分比**；只有生视频后处理回传真值时才画进度条。
 *   C. **批量并发队列**：把 n>1 的串行 for 换成带限流的并发池，逐条进度、逐条重试。
 */
import { BRIDGE, bridgeToken } from "./bridge";

export type GenKind = "image" | "video" | "audio" | "music";

export type GenStatus =
  | "queued"
  | "running"
  | "cancelling"
  | "done"
  | "failed"
  | "cancelled";

export type GenJob = {
  job_id: string;
  kind: GenKind;
  label: string;
  status: GenStatus;
  /** 机器可读阶段名，如 await_provider / postprocess */
  stage: string;
  /** 中文阶段标签，直接可显示 */
  stage_label: string;
  /** 附注（例如上游提示） */
  note: string;
  /** 真实百分比；上游无信号时必须为 null —— 前端不得自行估算后覆盖 */
  progress: number | null;
  attempts: number;
  max_attempts: number;
  error: string;
  created_at: number;
  started_at: number;
  finished_at: number;
  updated_at: number;
  elapsed_ms: number;
  queue_ms: number;
  cancellable: boolean;
  result: Record<string, unknown> | null;
  meta: Record<string, unknown>;
};

export type GenStats = {
  submitted: number;
  done: number;
  failed: number;
  cancelled: number;
  running: number;
  queued: number;
  retained: number;
  concurrency: number;
  workers: number;
};

const TERMINAL: GenStatus[] = ["done", "failed", "cancelled"];

export function isTerminal(status: GenStatus): boolean {
  return TERMINAL.includes(status);
}

function headers(json = false): HeadersInit {
  const h: Record<string, string> = { "X-Shiguang-Token": bridgeToken() };
  if (json) h["Content-Type"] = "application/json";
  return h;
}

async function readJson(res: Response): Promise<any> {
  try {
    return await res.json();
  } catch {
    throw new Error(`桥接层返回非 JSON（HTTP ${res.status}）`);
  }
}

/** 提交生成任务，立即返回任务快照。 */
export async function submitGeneration(
  kind: GenKind,
  payload: Record<string, unknown>,
  opts: { label?: string; maxAttempts?: number } = {},
): Promise<GenJob> {
  const res = await fetch(`${BRIDGE}/host/generation/submit?token=${encodeURIComponent(bridgeToken())}`, {
    method: "POST",
    headers: headers(true),
    body: JSON.stringify({
      kind,
      payload,
      label: opts.label || "",
      max_attempts: opts.maxAttempts ?? 1,
    }),
  });
  const data = await readJson(res);
  if (!data?.ok) throw new Error(data?.message || `提交生成任务失败（HTTP ${res.status}）`);
  return data.job as GenJob;
}

export async function getGenerationJob(jobId: string): Promise<GenJob> {
  const res = await fetch(
    `${BRIDGE}/host/generation/status?token=${encodeURIComponent(bridgeToken())}&job_id=${encodeURIComponent(jobId)}`,
    { headers: headers() },
  );
  const data = await readJson(res);
  if (!data?.ok) throw new Error(data?.message || `查询任务失败（HTTP ${res.status}）`);
  return data.job as GenJob;
}

export async function cancelGeneration(jobId: string): Promise<{ ok: boolean; message?: string }> {
  try {
    const res = await fetch(`${BRIDGE}/host/generation/cancel?token=${encodeURIComponent(bridgeToken())}`, {
      method: "POST",
      headers: headers(true),
      body: JSON.stringify({ job_id: jobId }),
    });
    const data = await readJson(res);
    return { ok: Boolean(data?.ok), message: data?.message };
  } catch (e: any) {
    return { ok: false, message: String(e?.message || e) };
  }
}

export async function listGenerationJobs(limit = 30): Promise<{ jobs: GenJob[]; stats: GenStats | null }> {
  const res = await fetch(
    `${BRIDGE}/host/generation/list?token=${encodeURIComponent(bridgeToken())}&limit=${limit}`,
    { headers: headers() },
  );
  const data = await readJson(res);
  return { jobs: (data?.jobs || []) as GenJob[], stats: (data?.stats || null) as GenStats | null };
}

/** 轮询间隔：先密后疏，长任务不刷爆桥接层。 */
function pollDelay(elapsedMs: number): number {
  if (elapsedMs < 8_000) return 500;
  if (elapsedMs < 30_000) return 1_000;
  return 2_000;
}

export type AwaitOptions = {
  onProgress?: (job: GenJob) => void;
  signal?: AbortSignal;
  /** 轮询总超时（毫秒），默认 15 分钟；超时后抛出但不自动取消后端任务 */
  timeoutMs?: number;
};

/**
 * 等待任务抵达终态。取消方式二选一：
 *   ① `signal.abort()`（React 卸载 / 用户点取消）→ 会调用后端 cancel
 *   ② 直接 `cancelGeneration(jobId)`
 */
export async function awaitGeneration(jobId: string, opts: AwaitOptions = {}): Promise<GenJob> {
  const { onProgress, signal, timeoutMs = 15 * 60 * 1000 } = opts;
  const t0 = Date.now();
  let last: GenJob | null = null;

  for (;;) {
    if (signal?.aborted) {
      await cancelGeneration(jobId);
      throw new DOMException("已取消", "AbortError");
    }
    const job = await getGenerationJob(jobId);
    last = job;
    onProgress?.(job);
    if (isTerminal(job.status)) return job;
    if (Date.now() - t0 > timeoutMs) {
      throw new Error(`等待生成结果超时（${Math.round(timeoutMs / 1000)}s），任务仍在后台运行`);
    }
    await sleep(pollDelay(Date.now() - t0), signal);
  }
  // eslint-disable-next-line no-unreachable
  return last as GenJob;
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const t = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(t);
      reject(new DOMException("已取消", "AbortError"));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

/** 提交 + 等待，一步到位。失败时抛出带上游原文的错误。 */
export async function runGeneration(
  kind: GenKind,
  payload: Record<string, unknown>,
  opts: AwaitOptions & { label?: string; maxAttempts?: number } = {},
): Promise<{ job: GenJob; result: Record<string, unknown> }> {
  const submitted = await submitGeneration(kind, payload, {
    label: opts.label,
    maxAttempts: opts.maxAttempts,
  });
  opts.onProgress?.(submitted);
  const job = await awaitGeneration(submitted.job_id, opts);
  if (job.status === "cancelled") throw new DOMException("已取消", "AbortError");
  if (job.status !== "done") throw new Error(job.error || "生成失败");
  return { job, result: (job.result || {}) as Record<string, unknown> };
}

// ── 批量并发池（P0-3）─────────────────────────────────────────────────

export type PoolTask<P> = { key: string; payload: P; label?: string };

export type PoolItem<P> = {
  key: string;
  label: string;
  payload: P;
  status: GenStatus | "pending";
  stage_label: string;
  progress: number | null;
  elapsed_ms: number;
  attempts: number;
  error: string;
  job_id: string;
  result: Record<string, unknown> | null;
};

export type PoolOptions<P> = {
  concurrency?: number;
  /** 每条任务的重试次数（后端退避重试），默认 2 次 */
  maxAttempts?: number;
  onItem?: (item: PoolItem<P>, index: number, all: PoolItem<P>[]) => void;
  onDone?: (all: PoolItem<P>[]) => void;
  signal?: AbortSignal;
};

/**
 * 并发池执行批量生成：**逐条进度、逐条重试、逐条可取消**。
 * 返回时 `all` 与结果同序，调用方可直接按 index 回填 UI。
 */
export async function runGenerationPool<P extends Record<string, unknown>>(
  kind: GenKind,
  tasks: PoolTask<P>[],
  opts: PoolOptions<P> = {},
): Promise<PoolItem<P>[]> {
  const concurrency = Math.max(1, Math.min(8, opts.concurrency ?? 3));
  const maxAttempts = Math.max(1, opts.maxAttempts ?? 2);
  const items: PoolItem<P>[] = tasks.map((t, i) => ({
    key: t.key,
    label: t.label || `第 ${i + 1} 条`,
    payload: t.payload,
    status: "pending",
    stage_label: "待开始",
    progress: null,
    elapsed_ms: 0,
    attempts: 0,
    error: "",
    job_id: "",
    result: null,
  }));

  const emit = (i: number) => opts.onItem?.(items[i], i, items);

  let cursor = 0;
  const worker = async (): Promise<void> => {
    for (;;) {
      if (opts.signal?.aborted) return;
      const i = cursor++;
      if (i >= items.length) return;
      const item = items[i];
      try {
        const submitted = await submitGeneration(kind, item.payload, {
          label: item.label,
          maxAttempts,
        });
        item.job_id = submitted.job_id;
        item.status = submitted.status;
        item.stage_label = submitted.stage_label;
        emit(i);
        const final = await awaitGeneration(submitted.job_id, {
          signal: opts.signal,
          onProgress: (j) => {
            item.status = j.status;
            item.stage_label = j.stage_label;
            item.progress = j.progress;
            item.elapsed_ms = j.elapsed_ms;
            item.attempts = j.attempts;
            emit(i);
          },
        });
        if (final.status === "done") {
          item.status = "done";
          item.result = final.result;
          item.progress = final.progress;
        } else {
          item.status = final.status;
          item.error = final.error || "生成失败";
        }
        item.elapsed_ms = final.elapsed_ms;
        item.attempts = final.attempts;
      } catch (e: any) {
        if (e?.name === "AbortError") {
          item.status = "cancelled";
          item.error = "已取消";
        } else {
          item.status = "failed";
          item.error = String(e?.message || e);
        }
      }
      emit(i);
    }
  };

  await Promise.all(Array.from({ length: Math.min(concurrency, items.length) }, () => worker()));
  opts.onDone?.(items);
  return items;
}

/** 取消整批（逐条发给后端，互不影响已完成的）。 */
export async function cancelPool<P>(items: PoolItem<P>[]): Promise<void> {
  await Promise.all(
    items
      .filter((it) => it.job_id && !isTerminal(it.status as GenStatus))
      .map((it) => cancelGeneration(it.job_id)),
  );
}
