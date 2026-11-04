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
  listVideoModels,
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

/** 「自动」通道：不手选模型，交给执行层（/host/execution-plan）裁定本地/云端顺序。 */
export const AUTO_CHANNEL_ID = "auto";

/** 纯文生视频的本地模型（没有首帧也能跑；其余本机模型按图生视频处理）。 */
const TEXT_ONLY_LOCAL_VIDEO = new Set(["wan21-t2v-1.3b"]);

export type VideoChainHop = "local" | "cloud";

/**
 * 纯函数：把执行层计划收敛成**本次实际可尝试**的顺序。
 *
 * 诚实边界：
 *   · 本地 SVD 是 i2v ⇒ 没有首帧就**不排本地**（而不是排了再报错）；
 *   · 云端需要兜底模型 ⇒ 没配就不排云端；
 *   · 两者都被排除时报空链 + 原因（调用方如实提示，绝不假装生成了）。
 */
export function buildVideoChain(
  plan: { chain?: unknown } | null,
  opts: { hasReference: boolean; cloudFallback: boolean },
): { chain: VideoChainHop[]; reasons: string[] } {
  const reasons: string[] = [];
  const raw = Array.isArray(plan?.chain) ? (plan!.chain as string[]) : [];
  const wanted = raw.filter((h) => h === "local" || h === "cloud") as VideoChainHop[];
  const seq: VideoChainHop[] = wanted.length ? wanted : ["cloud"];
  const chain: VideoChainHop[] = [];
  for (const hop of seq) {
    if (hop === "local" && !opts.hasReference) {
      reasons.push("本地 SVD 需要首帧图，本次没有 ⇒ 跳过本地");
      continue;
    }
    if (hop === "cloud" && !opts.cloudFallback) {
      reasons.push("没有可用的云端兜底模型 ⇒ 跳过云端");
      continue;
    }
    if (!chain.includes(hop)) chain.push(hop);
  }
  if (!chain.length) reasons.push("本地与云端都不可做（缺首帧且无云端模型）");
  return { chain, reasons };
}

/** auto 模式的云端兜底：取第一个**非本地**渠道模型；取不到返回 undefined（链收敛时跳过云端）。 */
async function pickCloudVideoFallback(): Promise<
  { channel_id: string; model: string } | undefined
> {
  try {
    const res = await listVideoModels();
    const opt = (res.models || []).find(
      (m) => m.channel_id && m.channel_id !== LOCAL_CHANNEL_ID && m.channel_id !== AUTO_CHANNEL_ID,
    );
    return opt ? { channel_id: opt.channel_id, model: opt.model } : undefined;
  } catch {
    return undefined;
  }
}

/** 取执行层计划；失败返回 null，调用方按「云端优先」兜底（不因调度层异常中断生成）。 */
export async function fetchVideoExecutionPlan(
  hasReference: boolean,
): Promise<{ chain?: string[]; reasons?: string[] } | null> {
  try {
    const res = await fetch(
      `${BRIDGE}/host/execution-plan?capability=video&has_reference=${hasReference ? 1 : 0}`,
      { headers: authHeaders(), cache: "no-store" },
    );
    const data = await res.json();
    return data && data.ok && data.plan ? data.plan : null;
  } catch {
    return null;
  }
}

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
    const modes = (m.modes || [])
      .map((mode) => (mode === "t2v" ? "文生视频" : mode === "i2v" ? "图生视频" : mode))
      .join("/");
    return {
      channel_id: LOCAL_CHANNEL_ID,
      channel_name: "本地",
      model: m.id,
      label: `本地 · ${m.label} · ${modes ? `${modes} · ` : ""}${m.params} · ${size} · 需 ${m.vram_gb}GB 显存 / ${m.ram_gb}GB 内存`,
    };
  });
  const auto: VideoModelOption = {
    channel_id: AUTO_CHANNEL_ID,
    channel_name: "自动",
    model: "",
    label: "自动 · 执行层调度（本地 SVD ↔ 云端，按算力滑块）",
  };
  return [auto, ...(cloud || []), ...opts];
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
  /** ★ 2026-11-01 修：原实现**整体丢弃提示词**（签名里根本没有）——
   *  后端 `body.get("prompt")` 恒为空，非 SVD 族直接报「提示词为空」，
   *  SVD 族虽不报错但运镜/内容完全不受提示词控制。 */
  prompt?: string;
  /** ★ 2026-11-01 修：尾帧原样透传（本地多数族不吃尾帧，由后端如实拒绝，前端不代判）。 */
  lastFrame?: string;
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
        prompt: opts.prompt || "",
        last_frame: opts.lastFrame || "",
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
  /** ★ 2026-11-01 修：尾帧（`node.data.lastFrameUrl`）。此前**从未下发**——
   *  画布早就能选尾帧（CanvasShell 的 onPick 写 lastFrameUrl），但生成请求不带它，
   *  所以云端「首尾帧」永远缺尾帧。 */
  lastFrame?: string;
  duration: number;
  quality: string;
  size?: string;
  awaitOpts?: Parameters<typeof generateVideoViaHost>[0]["awaitOpts"];
  /** 云端兜底渠道（auto 模式第二跳用；缺省则该跳不可用）。 */
  cloudFallback?: { channel_id: string; model: string };
  /** 本地视频模型 id（auto 模式第一跳用；缺省交后端默认 svd-xt-i2v）。 */
  localModel?: string;
}): Promise<{
  ok: boolean;
  message: string;
  video_url: string;
  video_path: string;
  /** 本次实际命中的路径（local / cloud）；失败为空串 */
  route_used?: string;
  /** 实际尝试顺序（可解释，R9） */
  chain_tried?: string[];
}> {
  const { channel_id, model } = opts.parsed;

  // ── 自动双路：执行层裁顺序，本地/云端依次尝试 ──
  if (channel_id === AUTO_CHANNEL_ID) {
    const hasReference = Boolean(opts.referenceImage);
    const fallback = opts.cloudFallback ?? (await pickCloudVideoFallback());
    const plan = await fetchVideoExecutionPlan(hasReference);
    const { chain, reasons } = buildVideoChain(plan, {
      hasReference,
      cloudFallback: Boolean(fallback),
    });
    const tried: string[] = [];
    let lastError = "";
    for (const hop of chain) {
      if (hop === "local") {
        tried.push("local");
        const lr = await generateVideoLocalViaHost({
          image: opts.referenceImage,
          prompt: opts.prompt,
          lastFrame: opts.lastFrame,
          model: opts.localModel || "",
          seconds: Math.max(1, Math.min(4, opts.duration || 2)),
          fps: 7,
          seed: 0,
        });
        if (lr.ok) {
          return {
            ok: true,
            message: `本地 SVD 成功（${lr.message || "已生成"}）`,
            video_url: lr.video_url || "",
            video_path: lr.video_path || "",
            route_used: "local",
            chain_tried: tried,
          };
        }
        lastError = lr.message || "本地 SVD 失败";
        continue;
      }
      if (!fallback) continue;
      tried.push("cloud");
      const res = await generateVideoViaHost({
        prompt: opts.prompt,
        model: fallback.model,
        channel_id: fallback.channel_id,
        duration: opts.duration,
        ...(opts.size ? { size: opts.size } : {}),
        reference_image: opts.referenceImage,
        // 首尾帧只在**真有尾帧**时才下发：无尾帧的调用方逐键与改动前一致
        ...(opts.lastFrame
          ? { first_frame: opts.referenceImage, last_frame: opts.lastFrame }
          : {}),
        quality: opts.quality,
        awaitOpts: opts.awaitOpts,
      });
      if (res.ok) {
        return {
          ok: true,
          message: `云端成功（${res.message || "已生成"}）`,
          video_url: String(res.video_url || ""),
          video_path: String(res.video_path || ""),
          route_used: "cloud",
          chain_tried: tried,
        };
      }
      lastError = String(res.message || "云端失败");
    }
    return {
      ok: false,
      message: `视频双路都失败：${lastError || "无可用路径"}${
        reasons.length ? "（" + reasons.join("；") + "）" : ""
      }`,
      video_url: "",
      video_path: "",
      route_used: "",
      chain_tried: tried,
    };
  }

  // ── 本机模型（diffusers）──
  if (channel_id === LOCAL_CHANNEL_ID) {
    if (!opts.referenceImage && !TEXT_ONLY_LOCAL_VIDEO.has(model)) {
      return {
        ok: false,
        message: "该本地视频模型需要首帧图，请先给节点配一张首帧图（Wan 2.1 T2V 可直接文生视频）",
        video_url: "",
        video_path: "",
      };
    }
    const lr = await generateVideoLocalViaHost({
      image: opts.referenceImage,
      prompt: opts.prompt,
      lastFrame: opts.lastFrame,
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
    // 同上：无尾帧 ⇒ 不下发首尾帧字段，云端行为逐键不变
    ...(opts.lastFrame
      ? { first_frame: opts.referenceImage, last_frame: opts.lastFrame }
      : {}),
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
