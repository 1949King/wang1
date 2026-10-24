/**
 * codeVideo 渲染客户端（V4.46 · 2026-10-20）
 *
 * 纯逻辑（payload 解析 / 事件过滤）+ 两个薄 fetch；节点组件只做 UI。
 * 后端契约：POST /host/code-video/render → { ok, job }；GET /host/code-video/status。
 */
import { BRIDGE, authHeaders } from "./bridge";
import { subscribeAgentEvents, type AgentEventEnvelope } from "./agentEvents";

export const CODE_VIDEO_RENDER_PATH = "/host/code-video/render";
export const CODE_VIDEO_STATUS_PATH = "/host/code-video/status";

export type CodeVideoJob = {
  id: string;
  status: "queued" | "running" | "done" | "error";
  stage: string;
  percent: number;
  detail?: string;
  error?: string;
  result?: Record<string, unknown> | null;
};

export type CodeVideoPayload = {
  spec?: Record<string, unknown>;
  storyboard?: unknown[];
  output_name?: string;
  qc?: boolean;
};

/** 从节点 textarea 解析 payload：JSON 对象=spec，JSON 数组=storyboard。 */
export function parseCodeVideoInput(
  raw: string,
  opts: { outputName?: string; qc?: boolean } = {},
): { payload?: CodeVideoPayload; error?: string } {
  const text = (raw || "").trim();
  if (!text) return { error: "请输入分镜表 JSON（数组）或 CodeVideoSpec JSON（对象）" };
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch (e: any) {
    return { error: `JSON 解析失败：${e?.message || e}` };
  }
  const payload: CodeVideoPayload = { qc: opts.qc !== false };
  if (Array.isArray(parsed)) {
    payload.storyboard = parsed;
  } else if (parsed && typeof parsed === "object") {
    payload.spec = parsed as Record<string, unknown>;
  } else {
    return { error: "JSON 必须是数组（分镜表）或对象（spec）" };
  }
  if (opts.outputName) payload.output_name = opts.outputName;
  return { payload };
}

export async function startCodeVideoRender(
  payload: CodeVideoPayload,
): Promise<{ ok: boolean; job?: CodeVideoJob; error?: string }> {
  try {
    const res = await fetch(`${BRIDGE}${CODE_VIDEO_RENDER_PATH}`, {
      method: "POST",
      headers: authHeaders(true),
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data?.ok) {
      return { ok: false, error: data?.message || data?.error || `HTTP ${res.status}` };
    }
    return { ok: true, job: data.job as CodeVideoJob };
  } catch (e: any) {
    return { ok: false, error: `请求失败：${e?.message || e}` };
  }
}

export async function getCodeVideoJob(
  jobId: string,
): Promise<CodeVideoJob | null> {
  try {
    const params = new URLSearchParams({ job_id: jobId });
    const res = await fetch(`${BRIDGE}${CODE_VIDEO_STATUS_PATH}?${params.toString()}`, {
      headers: authHeaders(false),
    });
    if (!res.ok) return null;
    const data = await res.json().catch(() => ({}));
    return (data?.job as CodeVideoJob) || null;
  } catch {
    return null;
  }
}

/** 订阅某个 job 的 SSE（code_video.progress/done/error）；返回取消函数。 */
export function subscribeCodeVideoJob(
  jobId: string,
  onJob: (job: Partial<CodeVideoJob> & { id: string }) => void,
  onError?: (err: string) => void,
): () => void {
  return subscribeAgentEvents({
    onError,
    onEvent: (evt: AgentEventEnvelope) => {
      if (!evt?.type?.startsWith("code_video.")) return;
      const payload = (evt.payload || {}) as Record<string, unknown>;
      if (payload.job_id !== jobId) return;
      if (evt.type === "code_video.progress") {
        onJob({
          id: jobId,
          status: "running",
          stage: String(payload.stage || ""),
          percent: Number(payload.percent || 0),
          detail: String(payload.detail || ""),
        });
      } else if (evt.type === "code_video.done") {
        onJob({
          id: jobId,
          status: "done",
          stage: "done",
          percent: 100,
          result: (payload.result || {}) as Record<string, unknown>,
        });
      } else if (evt.type === "code_video.error") {
        onJob({
          id: jobId,
          status: "error",
          stage: "error",
          error: String(payload.error || "渲染失败"),
        });
      }
    },
  });
}
