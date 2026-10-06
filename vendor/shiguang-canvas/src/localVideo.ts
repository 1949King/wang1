/**
 * localVideo.ts — 本机（diffusers）视频生成的**画布侧唯一入口**
 *
 * 为什么单独成文件：单文件规模守卫（阈值 2000 行，**存量冻结只许减不许增**）。
 * 这块逻辑原本落在 `bridge.ts`（+132 行，超容差）与 `App.tsx`（2044 行，越线），
 * 拆出来之后两者都回落到基线内 —— 与本项目 `editor_agent_*_mixin` 的拆分先例同一思路。
 *
 * 与云端的边界：
 *   - 云端走 `bridge.generateVideoViaHost`（`channel::model` 选渠道）
 *   - 本机走 `POST /host/local-video-generate`（通道 id 固定 `"local"`）
 *   - **分支只存在于本文件的 `generateVideoUnified` 一处** ——
 *     云端/本地各写一条调用链是本项目反复出现的反模式（一侧改行为另一侧必漂移）。
 */
import {
  BRIDGE,
  authHeaders,
  bridgeToken,
  generateVideoViaHost,
  type VideoModelOption,
} from "./bridge";

/** 本机视频模型条目（本机 diffusers 模型，**不是**云渠道模型）。 */
export type LocalVideoModel = {
  id: string;
  label: string;
  params: string;
  modes: string[];
  download_gb: number;
  vram_gb: number;
  ram_gb: number;
  note: string;
  license: string;
};

/** 本机模型的**通道 id 常量**（别在各处写裸串 "local"）。 */
export const LOCAL_CHANNEL_ID = "local";

/**
 * 本地视频模型注册表（**只读**：不下载权重、不加载模型）。
 *
 * 走 `POST /host/local-video-generate {action:"models"}`。
 * 返回 `downloaded` 让 UI 标出「已下/未下」，避免用户点了才发现要下 4~32GB。
 */
export async function listLocalVideoModels(): Promise<{
  models: LocalVideoModel[];
  available: boolean;
  unavailable_reason: string;
  downloaded: string[];
}> {
  const token = bridgeToken();
  try {
    const res = await fetch(`${BRIDGE}/host/local-video-generate`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({ action: "models", token }),
    });
    const data = await res.json();
    if (!data.ok) {
      return { models: [], available: false, unavailable_reason: "接口未返回 ok", downloaded: [] };
    }
    return {
      models: (data.models || []) as LocalVideoModel[],
      available: Boolean(data.available),
      unavailable_reason: String(data.unavailable_reason || ""),
      downloaded: (data.downloaded || []) as string[],
    };
  } catch {
    return { models: [], available: false, unavailable_reason: "无法连接本地服务", downloaded: [] };
  }
}

/**
 * 把本机模型并入云端视频模型列表，供同一处下拉展示（用户不用切界面）。
 *
 * label 带上「体积 / 是否已下载 / 显存内存需求」—— 避免误选跑不动、
 * 或点了才发现要下几十 GB 的模型。
 */
export function mergeLocalVideoModels(
  cloud: VideoModelOption[] | undefined,
  local: { models?: LocalVideoModel[]; downloaded?: string[] },
): VideoModelOption[] {
  const opts: VideoModelOption[] = (local.models || []).map((m) => {
    const has = (local.downloaded || []).includes(m.id);
    const size = has ? "已下载" : `需下载 ${m.download_gb}GB`;
    return {
      channel_id: LOCAL_CHANNEL_ID,
      channel_name: "本地",
      model: m.id,
      label: `本地 · ${m.label} · ${m.params} · ${size} · 需 ${m.vram_gb}GB 显存 / ${m.ram_gb}GB 内存`,
    };
  });
  return [...(cloud || []), ...opts];
}

/**
 * 本地视频生成（图生视频，走项目原生链路，**不经 ComfyUI、不经云渠道**）。
 *
 * ⚠️ 与 `generateVideoViaHost` 的三点关键差别：
 *  1. 输入是**图片**（`image`），不是 prompt —— 本机模型 SVD 是 i2v；
 *  2. **不自动下载模型**：没下会返回明确指引（含目标目录），绝不悄悄开拉几 GB；
 *  3. **慢**（实测约 13 秒/帧，10 帧约 130 秒），调用方必须按**长任务**处理。
 *
 * `video_url` 是 bridge 的 `/inbox_file/` URL（WebView 能直接播）；
 * 本地文件路径在 `video_path`（供后端/剪辑用，前端播不了）。
 */
export async function generateVideoLocalViaHost(opts: {
  image: string;
  model?: string;
  seconds?: number;
  fps?: number;
  seed?: number;
  out_path?: string;
}): Promise<{
  ok: boolean;
  message?: string;
  video_url?: string;
  video_path?: string;
  frames?: number;
}> {
  const token = bridgeToken();
  try {
    const res = await fetch(`${BRIDGE}/host/local-video-generate`, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify({
        action: "generate",
        image: opts.image,
        model_id: opts.model || "",
        seconds: opts.seconds ?? 1.5,
        fps: opts.fps ?? 7,
        seed: opts.seed ?? 0,
        out_path: opts.out_path || "",
        token,
      }),
    });
    const data = await res.json();
    return {
      ok: Boolean(data.ok),
      message: String(data.message || ""),
      video_url: String(data.video_url || ""),
      video_path: String(data.video_path || data.path || ""),
      frames: Number(data.frames || 0),
    };
  } catch (e) {
    return { ok: false, message: `本地视频生成请求失败：${String(e)}` };
  }
}

/**
 * 视频生成的**统一入口**：按 `parsed.channel_id` 决定走云端渠道还是**本机模型**。
 *
 * 为什么不各写一套：云端/本地各写一条调用链是本项目反复出现的反模式，
 * 任何一侧改行为另一侧必然悄悄漂移。所以分支只在这里存在一次，
 * 三处调用方（主生成 / 双模型对比 / 生成器·视频）共用。
 *
 * `size` 为可选参：**原本不传的调用方继续不传** ⇒ 云端行为逐键不变。
 */
export async function generateVideoUnified(opts: {
  parsed: { channel_id: string; model: string };
  prompt: string;
  referenceImage: string;
  duration: number;
  quality: string;
  size?: string;
  awaitOpts?: Parameters<typeof generateVideoViaHost>[0]["awaitOpts"];
}): Promise<{ ok: boolean; message: string; video_url: string; video_path: string }> {
  const { channel_id, model } = opts.parsed;

  // ── 本机模型（diffusers）──
  if (channel_id === LOCAL_CHANNEL_ID) {
    if (!opts.referenceImage) {
      return {
        ok: false,
        message: "本地视频模型是**图生视频**，请先给该节点配一张首帧图（或挂一张参考图）",
        video_url: "",
        video_path: "",
      };
    }
    const lr = await generateVideoLocalViaHost({
      image: opts.referenceImage,
      model,
      // 本机生成很慢（实测约 13 秒/帧），时长收到 1~4 秒，别让用户误设 10 秒等半小时
      seconds: Math.max(1, Math.min(4, opts.duration || 2)),
      fps: 7,
      seed: 0,
    });
    return {
      ok: lr.ok,
      message: lr.message || "",
      video_url: lr.video_url || "",
      video_path: lr.video_path || "",
    };
  }

  // ── 云端渠道（参数与行为同改动前，**逐键保持**：含 size 的调用方才带 size）──
  const res = await generateVideoViaHost({
    prompt: opts.prompt,
    model,
    channel_id,
    duration: opts.duration,
    ...(opts.size ? { size: opts.size } : {}),
    reference_image: opts.referenceImage,
    quality: opts.quality,
    awaitOpts: opts.awaitOpts,
  });
  return {
    ok: Boolean(res.ok),
    message: String(res.message || ""),
    video_url: String(res.video_url || ""),
    video_path: String(res.video_path || ""),
  };
}
