/**
 * 图片转3D + 全景生成宿主桥接（T5 项四，2026-11-20）。
 *
 * 图片转3D：POST /host/image-to-3d（异步任务）→ 轮询 /host/generation/status，
 * 范式完全镜像 hostInterpolate.ts（submit + poll + parse 纯函数）。
 * 深度模型缺失时后端诚实返回 ok:false + guidance，本层透传不冒充。
 * 产物为深度重建 2.5D GLB 网格（note 如实标注），非真体积/泼溅。
 *
 * 全景生成：POST /host/generate-panorama（同步薄路由，可选网关 H3，默认关），
 * 未启用 ⇒ ok:false + guidance；成功 ⇒ 等距柱状全景 data URL + 署名 MiniMax H3。
 */
import { BRIDGE, bridgeToken, authHeaders } from "./bridge";
import { getGenerationJob, isTerminal, type GenJob } from "./generationQueue";

export type ImageTo3dResult = {
  ok: boolean;
  modelUrl?: string;
  modelPath?: string;
  vertices?: number;
  faces?: number;
  culled?: number;
  fov?: number;
  engine?: string;
  note?: string;
  message?: string;
  guidance?: string;
};

/** 解析宿主 image-to-3d 终态 result（纯函数，可单测）。 */
export function parseImageTo3dResult(raw: unknown): ImageTo3dResult {
  if (!raw || typeof raw !== "object") return { ok: false, message: "宿主返回无效响应" };
  const r = raw as Record<string, unknown>;
  const ok = r.ok === true && typeof r.model_url === "string" && r.model_url.length > 0;
  return {
    ok,
    modelUrl: ok ? (r.model_url as string) : undefined,
    modelPath: typeof r.model_path === "string" ? r.model_path : undefined,
    vertices: typeof r.vertices === "number" ? r.vertices : undefined,
    faces: typeof r.faces === "number" ? r.faces : undefined,
    culled: typeof r.culled === "number" ? r.culled : undefined,
    fov: typeof r.fov === "number" ? r.fov : undefined,
    engine: typeof r.engine === "string" ? r.engine : undefined,
    note: typeof r.note === "string" ? r.note : undefined,
    message: typeof r.message === "string" ? r.message : typeof r.error === "string" ? r.error : undefined,
    guidance: typeof r.guidance === "string" ? r.guidance : undefined,
  };
}

/** 提交图片转3D任务，立即返回 job_id（不阻塞）。 */
export async function submitImageTo3d(opts: {
  image: string;
  fov?: number;
  maxSide?: number;
  title?: string;
}): Promise<{ ok: boolean; jobId?: string; message?: string }> {
  try {
    const resp = await fetch(`${BRIDGE}/host/image-to-3d`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({
        image: opts.image,
        fov: opts.fov ?? 60,
        max_side: opts.maxSide ?? 320,
        title: opts.title ?? "",
        token: bridgeToken(),
      }),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok || data.ok === false) {
      return { ok: false, message: data.message || data.error || `请求失败（${resp.status}）` };
    }
    return { ok: true, jobId: data.job_id };
  } catch (e) {
    return { ok: false, message: `无法连接画布桥：${String(e)}` };
  }
}

/**
 * 提交并轮询至终态（范式同 runInterpolate）。onStage 回调用于节点进度展示。
 * 失败/取消诚实返回 ok:false + message/guidance，不抛异常（调用方无需 try）。
 */
export async function runImageTo3d(
  opts: { image: string; fov?: number; maxSide?: number; title?: string },
  onStage?: (stage: string, progress: number | null) => void,
): Promise<ImageTo3dResult> {
  const sub = await submitImageTo3d(opts);
  if (!sub.ok || !sub.jobId) return { ok: false, message: sub.message || "提交失败" };
  const jobId = sub.jobId;
  // 轮询上限 ~10min（深度估计 + 网格重建通常 <30s，留足余量）
  for (let i = 0; i < 400; i++) {
    await new Promise((r) => setTimeout(r, 1500));
    let job: GenJob | null = null;
    try {
      job = await getGenerationJob(jobId);
    } catch {
      continue; // 瞬时网络抖动，继续轮询
    }
    if (!job) continue;
    onStage?.(job.stage_label || job.stage, job.progress);
    if (!isTerminal(job.status)) continue;
    if (job.status === "done" && job.result) {
      return parseImageTo3dResult(job.result);
    }
    const parsed = job.result ? parseImageTo3dResult(job.result) : null;
    return {
      ok: false,
      message: job.error || parsed?.message || (job.status === "cancelled" ? "已取消" : "图片转3D失败"),
      guidance: parsed?.guidance,
    };
  }
  return { ok: false, message: "图片转3D超时（任务仍在后台，可稍后在生成队列查看）" };
}

// ── 全景生成（可选网关 H3，同步薄封装）─────────────────────────────────────

export type PanoramaGenResult = {
  ok: boolean;
  imageDataUrl?: string;
  attribution?: string;
  message?: string;
  guidance?: string;
};

/** 解析宿主 generate-panorama 响应（纯函数，可单测）。 */
export function parsePanoramaResult(raw: unknown): PanoramaGenResult {
  if (!raw || typeof raw !== "object") return { ok: false, message: "宿主返回无效响应" };
  const r = raw as Record<string, unknown>;
  const url = typeof r.image_data_url === "string" ? r.image_data_url : "";
  const ok = r.ok === true && url.startsWith("data:image");
  return {
    ok,
    imageDataUrl: ok ? url : undefined,
    attribution: typeof r.attribution === "string" ? r.attribution : undefined,
    message: typeof r.message === "string" ? r.message : undefined,
    guidance: typeof r.guidance === "string" ? r.guidance : undefined,
  };
}

/** 经可选网关生成等距柱状全景（默认关；未启用诚实 ok:false + guidance）。 */
export async function generatePanorama(opts: {
  prompt: string;
  image?: string;
  model?: string;
  channelId?: string;
}): Promise<PanoramaGenResult> {
  try {
    const resp = await fetch(`${BRIDGE}/host/generate-panorama`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders() },
      body: JSON.stringify({
        prompt: opts.prompt,
        image: opts.image || "",
        model: opts.model || "",
        channel_id: opts.channelId || "",
        token: bridgeToken(),
      }),
    });
    const data = await resp.json().catch(() => ({}));
    const res = parsePanoramaResult(data);
    if (!resp.ok && res.ok) return { ok: false, message: res.message || `请求失败（${resp.status}）` };
    return res;
  } catch (e) {
    return { ok: false, message: `无法连接画布桥：${String(e)}` };
  }
}
