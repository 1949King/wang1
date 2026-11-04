/** 与拾光剪影 canvas_bridge (:18765) 对接 */

// 注意：与 generationQueue 存在「延迟引用」循环 import（双方模块顶层均不触碰对方绑定，
// 仅在函数调用时使用），ESM 下安全。
import { runGeneration, type AwaitOptions } from "./generationQueue";

// 默认后端地址（兼容 Qt WebEngine 嵌入场景）；Tauri 模式下由
// ensureTauriBridgeCredentials() 通过 invoke 拿到 Python 后端实际端口后覆盖。
export let BRIDGE = "http://127.0.0.1:18765";
const CONFIG_KEY = "infinite-canvas:ai_config_store";

export type BridgePrefs = {
  character_id?: string;
  character_name?: string;
  character_prompt?: string;
  enable_interpolation?: boolean;
  active_provider?: string;
  active_provider_label?: string;
};

export type ImageModelOption = {
  channel_id: string;
  channel_name: string;
  model: string;
  label: string;
};

function tokenFromQuery(): string {
  try {
    return new URLSearchParams(location.search).get("token") || "";
  } catch {
    return "";
  }
}

/**
 * Tauri 桌面环境下从 Rust 端拉取 Python 后端的本会话凭据并写入 window 全局变量，
 * 同时重新赋值 BRIDGE 为后端实际 URL。Qt WebEngine 嵌入场景下此函数 no-op。
 *
 * libtv/App.tsx 启动时需 await 此函数，之后 bridgeToken() / BRIDGE 才可用。
 */
export async function ensureTauriBridgeCredentials(): Promise<void> {
  if (typeof window === "undefined") return;
  const isTauri = "__TAURI__" in window || "__TAURI_INTERNALS__" in window;
  if (!isTauri) return;
  try {
    // 动态 import 避免非 Tauri 环境引入 @tauri-apps/api 失败
    const { invoke } = await import("@tauri-apps/api/core");
    const [token, url] = await Promise.all([
      invoke<string>("get_bridge_token").catch(() => ""),
      invoke<string>("get_bridge_url").catch(() => ""),
    ]);
    if (token) (window as any).__SHIGUANG_BRIDGE_TOKEN = token;
    if (url) {
      (window as any).__SHIGUANG_BRIDGE_URL = url;
      BRIDGE = url;
    }
  } catch (error) {
    console.warn("[libtv/bridge] ensureTauriBridgeCredentials failed:", error);
  }
}

export function bridgeToken(): string {
  // 优先级（2026-10-14 修正）：window（inject.js 每页现注入）→ URL ?token=（宿主
  // 加载页面时现注入）→ localStorage（**跨会话残留**，仅作最后兜底）。
  // 旧顺序把 localStorage 排在 URL 之前：一旦页面没跑到 inject.js，就会一直用
  // 上一会话的旧 token ⇒ 所有 /host/*（含 SSE）401 ⇒ EventSource 无限重连刷屏。
  return (
    (window as any).__SHIGUANG_BRIDGE_TOKEN ||
    tokenFromQuery() ||
    localStorage.getItem("__shiguang_bridge_token") ||
    ""
  );
}

/**
 * 凭据自愈：从宿主 /inject.js 重新拉取**当前会话** token。
 *
 * 背景（2026-10-14 实测事故）：后端 `_SESSION_TOKEN` 每次启动随机重建，而 localStorage
 * 里的旧 token 会跨会话残留。页面若没跑到 inject.js，就会拿旧 token 打所有 /host/*
 * （含 SSE）⇒ 401 ⇒ EventSource 无限自动重连刷屏。inject.js 始终携带当前 token，
 * 故用它做自愈源头。成功后同步刷新 window 与 localStorage，返回 token（失败返回 ""）。
 */
export async function refreshBridgeTokenFromInject(): Promise<string> {
  try {
    const res = await fetch(`${BRIDGE}/inject.js?t=${Date.now()}`, { cache: "no-store" });
    if (!res.ok) return "";
    const text = await res.text();
    const matched = text.match(/var\s+TOKEN\s*=\s*"([0-9a-fA-F]{16,})"/);
    const token = matched ? matched[1] : "";
    if (!token) return "";
    (window as any).__SHIGUANG_BRIDGE_TOKEN = token;
    try {
      localStorage.setItem("__shiguang_bridge_token", token);
    } catch {
      /* localStorage 不可用时仅保留 window 值 */
    }
    return token;
  } catch {
    return "";
  }
}

export function authHeaders(json = false): HeadersInit {
  const h: Record<string, string> = {
    "X-Shiguang-Token": bridgeToken(),
  };
  if (json) h["Content-Type"] = "application/json";
  return h;
}

/** 经 canvas_bridge 代理拉 GitHub raw JSON（Qt WebView 直连常失败） */
export async function fetchJsonViaHost(url: string): Promise<unknown> {
  const token = bridgeToken();
  const res = await fetch(
    `${BRIDGE}/host/prompt-fetch?token=${encodeURIComponent(token)}&url=${encodeURIComponent(url)}`,
    { headers: authHeaders() },
  );
  let data: { ok?: boolean; message?: string; data?: unknown };
  try {
    data = await res.json();
  } catch {
    throw new Error(`HTTP ${res.status}`);
  }
  if (!data.ok) {
    throw new Error(data.message || `HTTP ${res.status}`);
  }
  return data.data;
}

/** 经 canvas_bridge 读取仓库内 public/prompts 离线包（dist 未含 bundled 时仍可用） */
export async function fetchBundledPromptViaHost(sourceId: string): Promise<unknown> {
  const token = bridgeToken();
  const res = await fetch(
    `${BRIDGE}/host/prompt-bundled?token=${encodeURIComponent(token)}&source_id=${encodeURIComponent(sourceId)}`,
    { headers: authHeaders() },
  );
  let data: { ok?: boolean; message?: string; data?: unknown };
  try {
    data = await res.json();
  } catch {
    throw new Error(`HTTP ${res.status}`);
  }
  if (!data.ok) {
    throw new Error(data.message || `HTTP ${res.status}`);
  }
  return data.data;
}

/** 提示词封面/参考图 URL（Qt WebView 内优先走 bridge 代理） */
export function promptImageSrc(url: string): string {
  if (!url || url.startsWith("data:") || url.startsWith("blob:")) return url;
  try {
    const u = new URL(url);
    if (u.protocol !== "http:" && u.protocol !== "https:") return url;
  } catch {
    return url;
  }
  const token = bridgeToken();
  if (!token) return url;
  return `${BRIDGE}/host/prompt-image?token=${encodeURIComponent(token)}&url=${encodeURIComponent(url)}`;
}

export async function fetchPrefs(): Promise<BridgePrefs> {
  const token = bridgeToken();
  try {
    const res = await fetch(
      `${BRIDGE}/host/prefs?token=${encodeURIComponent(token)}`,
      { headers: authHeaders() },
    );
    if (!res.ok) return {};
    return (await res.json()) as BridgePrefs;
  } catch {
    return {};
  }
}

export async function listImageModels(): Promise<{
  models: ImageModelOption[];
  default: string;
  warnings?: string[];
  active_provider_label?: string;
  has_image_models?: boolean;
}> {
  const token = bridgeToken();
  try {
    const res = await fetch(
      `${BRIDGE}/host/image-models?token=${encodeURIComponent(token)}`,
      { headers: authHeaders() },
    );
    const data = await res.json();
    if (!data.ok) return { models: [], default: "", warnings: [data.message || "未授权或桥未就绪"] };
    return {
      models: (data.models || []) as ImageModelOption[],
      default: String(data.default || ""),
      warnings: (data.warnings || []) as string[],
      active_provider_label: String(data.active_provider_label || ""),
      has_image_models: Boolean(data.has_image_models ?? (data.models || []).length),
    };
  } catch {
    return { models: [], default: "", warnings: ["无法连接宿主桥 :18765，请确认已打开 AI 画布模块"] };
  }
}

/** 去重：同一 GFPGAN 预载 job 只跑一条前端轮询（批量生图会多次触发同一 job_id） */
const _modelPreloadInflight = new Set<string>();

export async function generateImageViaHost(opts: {
  prompt: string;
  model?: string;
  channel_id?: string;
  size?: string;
  /** 画幅（portrait 竖屏短剧 / landscape 横屏 / square 方形）。
   *  不传时后端缺省 portrait —— 本产品是竖屏短剧，横版默认是历史遗留缺陷（V4.40.10 修复）。 */
  aspect?: string;
  reference_image?: string;
  strength?: number;
  n?: number;
  quality?: string;
  /** 显式种子（抽卡复现 / 账本 best_seed 锁定）。不传则由后端自动生成随机种子并回显。
   *  批量（n>1）时勿传——每次调用共用同一种子会产出雷同结果，抽卡意义全无。 */
  seed?: number;
  /** 人脸修复模型后台预载进度回调（GFPGAN 下载期间异步上报，不阻塞生图返回） */
  onPreloadProgress?: (p: { progress: number; message: string }) => void;
  /** 异步任务化选项：signal 可取消，onProgress 如实上报阶段/进度（progress 为 null 时只有阶段与已用时）。
   *  不传则行为等价于旧同步端点（await 到底、无中途进度、不可取消）。 */
  awaitOpts?: AwaitOptions & { maxAttempts?: number };
}): Promise<{
  ok: boolean;
  message?: string;
  image_data_url?: string;
  image_url?: string;
  images?: string[];
  model?: string;
  mode?: string;
  img2img_fallback?: boolean;
  fallback_placeholder?: boolean;
  /** 实际使用的种子（后端缺省自动生成，恒回显） */
  seed?: number;
  /** 种子是否真发给了渠道（false=该渠道不支持/未透传，无法用种子复现，账本勿记 best_seed） */
  seed_sent?: boolean;
  /** 批量模式：每张图各自的种子（与 images 对齐） */
  seeds?: number[];
  /** 画质档含人脸修复时后端自动触发的 GFPGAN 后台预载任务 id（据此轮询 /host/model-preload） */
  preload_job_id?: string;
  /** 触发时人脸修复模型是否已就绪（true=可走 GFPGAN，false=本次暂时回退区域超分） */
  face_restore_ready?: boolean;
}> {
  const count = Math.max(1, Math.min(4, opts.n || 1));
  if (count === 1) {
    let data: {
      ok: boolean;
      message?: string;
      image_data_url?: string;
      image_url?: string;
      images?: string[];
      model?: string;
      mode?: string;
      img2img_fallback?: boolean;
      fallback_placeholder?: boolean;
      seed?: number;
      seed_sent?: boolean;
      preload_job_id?: string;
      face_restore_ready?: boolean;
    };
    try {
      // 异步任务化（submit + 轮询等待）：服务端 _GEN_PAYLOAD_KEYS 白名单与旧同步端点
      // 逐键一致，_build_gen_callable 为保真搬运（画质换算 / NG 计数 / GFPGAN 预载全保留）。
      // seed 仅在显式传入时进 payload（缺省保持旧 payload 形状，由后端自动生成并回显）。
      const explicitSeed =
        typeof opts.seed === "number" && Number.isFinite(opts.seed) && opts.seed > 0
          ? Math.floor(opts.seed)
          : null;
      const { result } = await runGeneration(
        "image",
        {
          prompt: opts.prompt,
          model: opts.model || "",
          channel_id: opts.channel_id || "",
          size: opts.size || "",
          aspect: opts.aspect || "",
          reference_image: opts.reference_image || "",
          strength: opts.strength ?? 0.65,
          quality: opts.quality || "standard",
          ...(explicitSeed !== null ? { seed: explicitSeed } : {}),
        },
        {
          signal: opts.awaitOpts?.signal,
          onProgress: opts.awaitOpts?.onProgress,
          timeoutMs: opts.awaitOpts?.timeoutMs,
          maxAttempts: opts.awaitOpts?.maxAttempts ?? 1,
          label: (opts.prompt || "").slice(0, 24),
        },
      );
      data = result as typeof data;
    } catch (e: any) {
      // runGeneration 约定：失败抛 Error(上游原文)，取消抛 DOMException(AbortError)
      if (e?.name === "AbortError") {
        return { ok: false, message: "已取消", fallback_placeholder: true };
      }
      return {
        ok: false,
        message: String(e?.message || e || "生成失败"),
        fallback_placeholder: true,
      };
    }
    // 命中人脸修复档且模型未就绪时，后台轮询预载进度（幂等去重），不阻塞本次生图返回
    const preloadJobId = data?.preload_job_id;
    if (
      opts.onPreloadProgress &&
      preloadJobId &&
      !data.face_restore_ready &&
      !_modelPreloadInflight.has(preloadJobId)
    ) {
      _modelPreloadInflight.add(preloadJobId);
      void waitForModelPreload(data, opts.onPreloadProgress).finally(() => {
        _modelPreloadInflight.delete(preloadJobId);
      });
    }
    return data;
  }
  const images: string[] = [];
  const seeds: number[] = [];
  let lastMsg = "";
  let okAny = false;
  for (let i = 0; i < count; i++) {
    // 批量抽卡：显式剥掉 opts.seed——多候选共用同一种子会产出雷同图，违背抽卡语义；
    // 每张由后端自动生成独立种子并回显，汇入 seeds[] 供账本记录。
    const one = await generateImageViaHost({ ...opts, seed: undefined, n: 1 });
    lastMsg = one.message || lastMsg;
    const url = one.image_data_url || one.image_url;
    if (one.ok && url) {
      images.push(url);
      if (typeof one.seed === "number") seeds.push(one.seed);
      okAny = true;
    }
  }
  return {
    ok: okAny,
    images,
    image_data_url: images[0],
    seeds,
    message: okAny
      ? `批量生图 ${images.length}/${count}`
      : lastMsg || "批量生图失败",
    fallback_placeholder: !okAny,
  };
}

// ── 本地模型（GFPGAN 人脸修复 ONNX）后台预载进度轮询 ──

export type ModelPreloadStatus = {
  ok: boolean;
  job_id?: string;
  kind?: string;
  status?: "processing" | "done";
  progress?: number;
  message?: string;
  ready?: boolean;
  updated_at?: number;
};

/** 触发 GFPGAN 后台预载（幂等），返回 job_id 供前端轮询 */
export async function startModelPreload(): Promise<{
  ok: boolean;
  job_id?: string;
  message?: string;
}> {
  const token = bridgeToken();
  try {
    const res = await fetch(`${BRIDGE}/host/model-preload?token=${encodeURIComponent(token)}`, {
      method: "POST",
      headers: authHeaders(true),
      body: "{}",
    });
    return await res.json();
  } catch (e) {
    return { ok: false, message: `预载触发失败: ${e}` };
  }
}

/** 轮询指定预载任务的进度；job_id 无效返回 ok=false */
export async function getModelPreloadStatus(jobId: string): Promise<ModelPreloadStatus> {
  const token = bridgeToken();
  try {
    const res = await fetch(`${BRIDGE}/host/model-preload?job_id=${encodeURIComponent(jobId)}`, {
      headers: { "X-Shiguang-Token": token },
    });
    return await res.json();
  } catch (e: any) {
    return { ok: false, message: e?.message || String(e) };
  }
}

/**
 * 若生图返回 preload_job_id 且 face_restore_ready=false，则后台预载尚未完成时，
 * 轮询直到 GFPGAN 就绪（或超时回退）。onProgress({ progress, message }) 供 UI 展示。
 * 与人脸修复无关（无 preload_job_id）时，直接返回未预载状态。
 */
export async function waitForModelPreload(
  result: {
    preload_job_id?: string;
    face_restore_ready?: boolean;
  },
  onProgress?: (p: { progress: number; message: string }) => void,
): Promise<{ ready: boolean; job_id: string; message: string }> {
  const jobId = result.preload_job_id || "";
  if (!jobId) {
    return { ready: false, job_id: "", message: "未触发" };
  }
  if (result.face_restore_ready) {
    return { ready: true, job_id: jobId, message: "人脸修复模型已就绪" };
  }
  const deadline = Date.now() + 30 * 60 * 1000; // 首次下载约 300MB，最多等 30 分钟
  let last = "";
  while (Date.now() < deadline) {
    const status = await getModelPreloadStatus(jobId);
    onProgress?.({ progress: status.progress || 0, message: status.message || "" });
    last = status.message || last;
    if (status.status === "done") {
      return {
        ready: !!status.ready,
        job_id: jobId,
        message: status.message || (status.ready ? "模型已就绪" : "模型下载失败，将回退区域超分"),
      };
    }
    await new Promise((r) => setTimeout(r, 1500));
  }
  return { ready: false, job_id: jobId, message: last || "预载超时，将回退区域超分" };
}

/** 经 canvas_bridge 调五维评分器做 AI 审阅，返回卡片质量分数与 passed/issues-found 状态 */
export async function reviewCanvasNodeViaHost(opts: {
  clip_id?: string;
  node_id?: string;
  path?: string;
  duration?: number;
  quality_scores?: Record<string, number | null>;
}): Promise<{
  ok: boolean;
  status?: "passed" | "issues-found";
  quality_score?: number;
  review?: {
    clip_id: string;
    dimensions: Record<string, number>;
    weighted_score: number;
    grade: string;
    should_drop: boolean;
    suggestions: string[];
    estimated_dims: string[];
    is_fully_estimated: boolean;
  };
  message?: string;
}> {
  const token = bridgeToken();
  const res = await fetch(
    `${BRIDGE}/host/canvas-ai-review?token=${encodeURIComponent(token)}`,
    {
      method: "POST",
      headers: authHeaders(true),
      body: JSON.stringify({
        clip_id: opts.clip_id || "",
        node_id: opts.node_id || "",
        path: opts.path || "",
        duration: opts.duration ?? 0,
        quality_scores: opts.quality_scores || {},
      }),
    },
  );
  try {
    return await res.json();
  } catch {
    return { ok: false, message: `HTTP ${res.status}` };
  }
}

/** 经 canvas_bridge 执行 ComfyUI 工作流（粘贴即用；dry_run 演练模式引擎缺位仍走通解析→落箱链路） */
export async function runComfyUIWorkflowViaHost(
  workflowJson: unknown,
  dryRun: boolean = false,
): Promise<{
  ok: boolean;
  dry_run?: boolean;
  raw_format?: string;
  node_ids?: string[];
  class_types?: string[];
  errors?: string[];
  warnings?: string[];
  missing_nodes?: string[];
  engine_available?: boolean;
  engine_running?: boolean;
  inbox_dir?: string;
  prompt_id?: string;
  images?: unknown[];
  paths?: string[];
  urls?: string[];
  message?: string;
  error?: string;
}> {
  const token = bridgeToken();
  try {
    const res = await fetch(
      `${BRIDGE}/host/comfyui/run?token=${encodeURIComponent(token)}`,
      {
        method: "POST",
        headers: authHeaders(true),
        body: JSON.stringify({ workflow_json: workflowJson, dry_run: dryRun }),
      },
    );
    return await res.json();
  } catch (e) {
    return { ok: false, message: `执行 ComfyUI 工作流失败: ${e}` };
  }
}

export type ComfyEngineStatus = {
  engine_dir: string;
  engine_valid: boolean;
  process_alive: boolean;
  host: string;
  port: number;
  diagnose: {
    available: boolean;
    base_url: string;
    error: string;
    suggestion: string;
  };
};

/** 查询内置 ComfyUI 引擎状态（含未安装诊断 / 安装指引）；失败返回 null */
export async function getComfyEngineStatus(): Promise<ComfyEngineStatus | null> {
  const token = bridgeToken();
  try {
    const res = await fetch(
      `${BRIDGE}/host/comfyui/status?token=${encodeURIComponent(token)}`,
      { headers: authHeaders() },
    );
    if (!res.ok) return null;
    const data = (await res.json()) as { ok?: boolean; status?: ComfyEngineStatus };
    return data.ok ? (data.status ?? null) : null;
  } catch {
    return null;
  }
}

export type ComfyImportOutcome = {
  ok: boolean;              // dry-run 解析是否成功
  engineMissing: boolean;   // 引擎未安装（需弹诊断）
  message: string;          // 状态栏简短文案
  detail?: string;          // 引擎未安装时的安装指引（供醒目展示）
};

/** 判断已解析 JSON 是否为 ComfyUI workflow（UI 的 nodes 数组 或 graph 的 class_type 对象） */
export function isComfyWorkflowJson(json: unknown): boolean {
  if (!json || typeof json !== "object" || Array.isArray(json)) return false;
  const o = json as Record<string, unknown>;
  if (Array.isArray(o.nodes)) return true;
  return Object.values(o).some(
    (v) => v && typeof v === "object" && "class_type" in (v as Record<string, unknown>),
  );
}

/** 判断剪贴板文本是否为 ComfyUI workflow JSON（仅同步解析，用于粘贴拦截判定） */
export function isComfyWorkflowText(text: string): boolean {
  const trimmed = (text || "").trim();
  if (!trimmed || trimmed[0] !== "{") return false;
  try {
    return isComfyWorkflowJson(JSON.parse(trimmed));
  } catch {
    return false;
  }
}

/** 导入 ComfyUI 工作流（dry-run 演练解析）。返回结构化结果，含引擎未安装诊断。 */
export async function importComfyWorkflowText(text: string): Promise<ComfyImportOutcome> {
  const trimmed = (text || "").trim();
  if (!trimmed) {
    return { ok: false, engineMissing: false, message: "剪贴板为空，请先在 ComfyUI 中复制工作流" };
  }
  let json: unknown;
  try {
    json = JSON.parse(trimmed);
  } catch {
    return { ok: false, engineMissing: false, message: "剪贴板内容不是有效 JSON，无法识别为 ComfyUI 工作流" };
  }
  if (!isComfyWorkflowJson(json)) {
    return {
      ok: false,
      engineMissing: false,
      message: "剪贴板内容不是 ComfyUI 工作流（缺少 nodes 数组或 class_type 结构）",
    };
  }
  const res = await runComfyUIWorkflowViaHost(json, true);
  if (res.ok) {
    const types = [...new Set(res.class_types || [])];
    const typeText = types.length ? `；节点类型：${types.slice(0, 6).join("、")}` : "";
    const engineMissing = res.engine_available === false;
    let detail: string | undefined;
    if (engineMissing) {
      const st = await getComfyEngineStatus();
      detail = st?.diagnose?.suggestion || "未检测到内置 ComfyUI 引擎，暂时无法真正生成图片";
    }
    return {
      ok: true,
      engineMissing,
      message: `ComfyUI 工作流已解析（dry-run）${res.message ? ` · ${res.message}` : ""}${typeText}`,
      detail,
    };
  }
  return {
    ok: false,
    engineMissing: false,
    message: `ComfyUI 工作流解析失败：${res.error || res.message || "未知错误"}`,
  };
}

export async function inpaintViaHost(opts: {
  prompt: string;
  image: string;
  mask: string;
  model?: string;
  channel_id?: string;
  size?: string;
}): Promise<{
  ok: boolean;
  message?: string;
  image_data_url?: string;
  image_url?: string;
  mode?: string;
}> {
  const token = bridgeToken();
  try {
    const res = await fetch(
      `${BRIDGE}/host/inpaint?token=${encodeURIComponent(token)}`,
      {
        method: "POST",
        headers: authHeaders(true),
        body: JSON.stringify({
          prompt: opts.prompt,
          image: opts.image,
          mask: opts.mask,
          model: opts.model || "",
          channel_id: opts.channel_id || "",
          size: opts.size || "768x1344",
        }),
      },
    );
    return await res.json();
  } catch (e) {
    return { ok: false, message: `inpaint 异常: ${e}` };
  }
}

export async function generateAudioViaHost(opts: {
  prompt: string;
  model?: string;
  channel_id?: string;
  voice?: string;
}): Promise<{ ok: boolean; message?: string; audio_url?: string; fallback_local?: boolean }> {
  const token = bridgeToken();
  try {
    const res = await fetch(
      `${BRIDGE}/host/generate-audio?token=${encodeURIComponent(token)}`,
      {
        method: "POST",
        headers: authHeaders(true),
        body: JSON.stringify({
          prompt: opts.prompt,
          model: opts.model || "",
          channel_id: opts.channel_id || "",
          voice: opts.voice || "",
        }),
      },
    );
    return await res.json();
  } catch (e) {
    return { ok: false, message: `生音频异常: ${e}` };
  }
}

/**
 * @deprecated 旧路径：转发到外部 Node canvas-agent（:17371，@basketikun/canvas-agent）。
 * 自研画布请用 {@link projectAgentChatViaHost}（走 /host/project-agent/chat → project_agent_chat → ai_engine）。
 * 本函数保留仅为兼容，AgentPanel 和画布内部均不调用。
 */
export async function generateMusicViaHost(opts: {
  prompt: string;
  model?: string;
  channel_id?: string;
  style?: string;
  lyrics?: string;
  title?: string;
  instrumental?: boolean;
}): Promise<{
  ok: boolean;
  message?: string;
  audio_url?: string;
  title?: string;
  model?: string;
  fallback_local?: boolean;
}> {
  const token = bridgeToken();
  try {
    const res = await fetch(
      `${BRIDGE}/host/generate-music?token=${encodeURIComponent(token)}`,
      {
        method: "POST",
        headers: authHeaders(true),
        body: JSON.stringify({
          prompt: opts.prompt,
          model: opts.model || "",
          channel_id: opts.channel_id || "",
          style: opts.style || "",
          lyrics: opts.lyrics || "",
          title: opts.title || "",
          instrumental: !!opts.instrumental,
        }),
      },
    );
    return await res.json();
  } catch (e) {
    return { ok: false, message: `音乐生成异常: ${e}` };
  }
}

export async function agentChatViaHost(
  message: string,
): Promise<{ ok: boolean; message?: string; reply?: string }> {
  const token = bridgeToken();
  try {
    const res = await fetch(
      `${BRIDGE}/host/agent/chat?token=${encodeURIComponent(token)}`,
      {
        method: "POST",
        headers: authHeaders(true),
        body: JSON.stringify({ message }),
      },
    );
    return await res.json();
  } catch (e) {
    return { ok: false, message: `Agent 代理异常: ${e}` };
  }
}

export type ChatModelProvider = {
  id: string;
  name: string;
  models: string[];
  configured: boolean;
  is_local?: boolean;
  active?: boolean;
};

export async function listChatModels(): Promise<{
  ok: boolean;
  providers: ChatModelProvider[];
  active_provider?: string;
  message?: string;
}> {
  const token = bridgeToken();
  try {
    const res = await fetch(
      `${BRIDGE}/host/chat-models?token=${encodeURIComponent(token)}`,
      { headers: authHeaders() },
    );
    return await res.json();
  } catch (e) {
    return { ok: false, providers: [], message: `无法读取对话模型: ${e}` };
  }
}

/** 插件 SDK generateText — 走项目 Agent 对话（不 apply 画布命令） */
export async function generateTextViaHost(opts: {
  prompt: string;
  provider?: string;
  model?: string;
}): Promise<{ ok: boolean; text?: string; message?: string }> {
  const res = await projectAgentChatViaHost({
    message: opts.prompt,
    provider: opts.provider,
    model: opts.model,
    apply: false,
  });
  return {
    ok: !!res.ok,
    text: res.reply || res.raw,
    message: res.message,
  };
}

export async function projectAgentChatViaHost(opts: {
  message: string;
  provider?: string;
  model?: string;
  apply?: boolean;
  canvas_context?: Record<string, unknown>;
  mode?: string;
  stream_id?: string;
  agent_mode?: string;
  session_id?: string;
}): Promise<{
  ok: boolean;
  message?: string;
  reply?: string;
  raw?: string;
  commands?: unknown[];
  results?: unknown[];
  applied?: boolean;
  provider?: string;
  model?: string;
  stream_id?: string;
  path?: string;
}> {
  const token = bridgeToken();
  try {
    const res = await fetch(
      `${BRIDGE}/host/project-agent/chat?token=${encodeURIComponent(token)}`,
      {
        method: "POST",
        headers: authHeaders(true),
        body: JSON.stringify({
          message: opts.message,
          provider: opts.provider || "",
          model: opts.model || "",
          apply: opts.apply !== false,
          canvas_context: opts.canvas_context || null,
          mode: opts.mode || "canvas_fast",
          stream_id: opts.stream_id || "",
          agent_mode: opts.agent_mode || "collaborative",
          session_id: opts.session_id || "",
        }),
      },
    );
    return await res.json();
  } catch (e) {
    return { ok: false, message: `项目 Agent 异常: ${e}` };
  }
}

export type ProjectTool = {
  extension_id: string;
  extension_name: string;
  extension_type: string;
  tool_id: string;
  tool_name: string;
  description?: string;
};

export async function listProjectTools(agentMode?: string): Promise<{
  ok: boolean;
  tools: ProjectTool[];
  capabilities?: { capability_id: string; description?: string }[];
  message?: string;
}> {
  const token = bridgeToken();
  try {
    const q = agentMode ? `&agent_mode=${encodeURIComponent(agentMode)}` : "";
    const res = await fetch(
      `${BRIDGE}/host/tools?token=${encodeURIComponent(token)}${q}`,
      { headers: authHeaders() },
    );
    return await res.json();
  } catch (e) {
    return { ok: false, tools: [], message: `无法列出工具: ${e}` };
  }
}

export async function runProjectToolViaHost(opts: {
  extension_id?: string;
  tool_id?: string;
  skill_id?: string;
  params?: Record<string, unknown>;
  agent_mode?: string;
  approved?: boolean;
  session_id?: string;
}): Promise<{ ok: boolean; message?: string; data?: unknown }> {
  const token = bridgeToken();
  try {
    const res = await fetch(
      `${BRIDGE}/host/tools/run?token=${encodeURIComponent(token)}`,
      {
        method: "POST",
        headers: authHeaders(true),
        body: JSON.stringify(opts),
      },
    );
    return await res.json();
  } catch (e) {
    return { ok: false, message: `运行工具失败: ${e}` };
  }
}

export async function controlAgentSession(opts: {
  session_id: string;
  action: "stop" | "pause" | "resume" | "continue" | "mode";
  mode?: string;
}): Promise<{ ok: boolean; mode?: string; message?: string }> {
  const token = bridgeToken();
  try {
    const res = await fetch(
      `${BRIDGE}/host/agent/session?token=${encodeURIComponent(token)}`,
      {
        method: "POST",
        headers: authHeaders(true),
        body: JSON.stringify(opts),
      },
    );
    return await res.json();
  } catch (e) {
    return { ok: false, message: String(e) };
  }
}

export type VideoModelOption = ImageModelOption;
export type AudioModelOption = ImageModelOption;
export type MusicModelOption = ImageModelOption;

export async function listAudioModels(): Promise<{
  models: AudioModelOption[];
  default: string;
  warnings?: string[];
  has_audio_models?: boolean;
}> {
  const token = bridgeToken();
  try {
    const res = await fetch(
      `${BRIDGE}/host/audio-models?token=${encodeURIComponent(token)}`,
      { headers: authHeaders() },
    );
    const data = await res.json();
    if (!data.ok) return { models: [], default: "" };
    return {
      models: (data.models || []) as AudioModelOption[],
      default: String(data.default || ""),
      warnings: (data.warnings || []) as string[],
      has_audio_models: Boolean(data.has_audio_models ?? (data.models || []).length),
    };
  } catch {
    return { models: [], default: "" };
  }
}

export async function listMusicModels(): Promise<{
  models: MusicModelOption[];
  default: string;
  warnings?: string[];
  has_music_models?: boolean;
}> {
  const token = bridgeToken();
  try {
    const res = await fetch(
      `${BRIDGE}/host/music-models?token=${encodeURIComponent(token)}`,
      { headers: authHeaders() },
    );
    const data = await res.json();
    if (!data.ok) return { models: [], default: "" };
    return {
      models: (data.models || []) as MusicModelOption[],
      default: String(data.default || ""),
      warnings: (data.warnings || []) as string[],
      has_music_models: Boolean(data.has_music_models ?? (data.models || []).length),
    };
  } catch {
    return { models: [], default: "" };
  }
}

export async function listVideoModels(): Promise<{
  models: VideoModelOption[];
  default: string;
  warnings?: string[];
  has_video_models?: boolean;
}> {
  const token = bridgeToken();
  try {
    const res = await fetch(
      `${BRIDGE}/host/video-models?token=${encodeURIComponent(token)}`,
      { headers: authHeaders() },
    );
    const data = await res.json();
    if (!data.ok) return { models: [], default: "" };
    return {
      models: (data.models || []) as VideoModelOption[],
      default: String(data.default || ""),
      warnings: (data.warnings || []) as string[],
      has_video_models: Boolean(data.has_video_models ?? (data.models || []).length),
    };
  } catch {
    return { models: [], default: "" };
  }
}


export async function generateVideoViaHost(opts: {
  prompt: string;
  model?: string;
  channel_id?: string;
  duration?: number;
  size?: string;
  reference_image?: string;
  /** 参考视频（motion-ref 模式 A）：inbox URL / data URL / 本地路径，后端统一落盘并做能力探测 */
  reference_video?: string;
  first_frame?: string;
  last_frame?: string;
  quality?: string;
  /** 异步任务化选项：signal 可取消，onProgress 如实上报阶段/进度
   * （视频后处理超分/补帧是整条链路唯一有真实百分比的阶段）。 */
  awaitOpts?: AwaitOptions & { maxAttempts?: number };
}): Promise<{
  ok: boolean;
  message?: string;
  video_url?: string;
  video_path?: string;
  model?: string;
  channel_id?: string;
  channel_name?: string;
  supports_motion_ref?: boolean;
  reference_video_url?: string;
  /** 后处理（超分/补帧）是否在后台执行中 */
  postprocessing?: boolean;
  /** 后处理任务 id，前端据此轮询 /host/video-postprocess */
  postprocess_job_id?: string;
}> {
  try {
    // 异步任务化（submit + 轮询等待）：白名单与旧同步端点逐键一致，保真搬运。
    const { result } = await runGeneration(
      "video",
      {
        prompt: opts.prompt,
        model: opts.model || "",
        channel_id: opts.channel_id || "",
        duration: opts.duration ?? 5,
        size: opts.size || "1280x720",
        reference_image: opts.reference_image || "",
        reference_video: opts.reference_video || "",
        first_frame: opts.first_frame || "",
        last_frame: opts.last_frame || "",
        quality: opts.quality || "standard",
      },
      {
        signal: opts.awaitOpts?.signal,
        onProgress: opts.awaitOpts?.onProgress,
        timeoutMs: opts.awaitOpts?.timeoutMs,
        maxAttempts: opts.awaitOpts?.maxAttempts ?? 1,
        label: (opts.prompt || "").slice(0, 24),
      },
    );
    return result as {
      ok: boolean;
      message?: string;
      video_url?: string;
      video_path?: string;
      model?: string;
      channel_id?: string;
      channel_name?: string;
      supports_motion_ref?: boolean;
      reference_video_url?: string;
      postprocessing?: boolean;
      postprocess_job_id?: string;
    };
  } catch (e: any) {
    if (e?.name === "AbortError") {
      return { ok: false, message: "已取消" };
    }
    return { ok: false, message: String(e?.message || e || "生成失败") };
  }
}

// ── 单视频后处理（超分/补帧）进度轮询 ──

export type VideoPostprocessStatus = {
  ok: boolean;
  job_id?: string;
  status?: "processing" | "done";
  progress?: number;
  message?: string;
  video_path?: string;
  video_url?: string;
  postprocessed?: boolean;
  updated_at?: number;
};

export async function getVideoPostprocessStatus(jobId: string): Promise<VideoPostprocessStatus> {
  const tok = bridgeToken();
  try {
    const res = await fetch(`${BRIDGE}/host/video-postprocess?job_id=${encodeURIComponent(jobId)}`, {
      headers: { "X-Shiguang-Token": tok },
    });
    return await res.json();
  } catch (e: any) {
    return { ok: false, message: e?.message || String(e) };
  }
}

/**
 * 若 generateVideoViaHost 返回 postprocessing=true，则轮询 /host/video-postprocess
 * 直到后处理（超分/补帧）完成，返回增强后的 url/path；否则原样返回。
 * onProgress({ progress, message }) 供 UI 展示进度（可选）。
 */
export async function waitForVideoPostprocess(
  result: {
    ok: boolean;
    video_url?: string;
    video_path?: string;
    postprocessing?: boolean;
    postprocess_job_id?: string;
  },
  onProgress?: (p: { progress: number; message: string }) => void,
): Promise<{ video_url: string; video_path: string; postprocessed: boolean }> {
  const base = {
    video_url: result.video_url || "",
    video_path: result.video_path || "",
    postprocessed: false,
  };
  if (!result.postprocessing || !result.postprocess_job_id) {
    return base;
  }
  const deadline = Date.now() + 15 * 60 * 1000; // 最多等 15 分钟
  while (Date.now() < deadline) {
    const status = await getVideoPostprocessStatus(result.postprocess_job_id);
    onProgress?.({ progress: status.progress || 0, message: status.message || "" });
    if (status.status === "done") {
      return {
        video_url: status.video_url || base.video_url,
        video_path: status.video_path || base.video_path,
        postprocessed: !!status.postprocessed,
      };
    }
    await new Promise((r) => setTimeout(r, 1500));
  }
  return base;
}

// ── 模式 B 姿态解析（视频 → 关键点 JSON 子进程） ──

export async function poseExtractViaHost(opts: {
  /** 参考视频：inbox URL / 本地路径 */
  video: string;
  /** 采样步长（1=逐帧） */
  sample_step?: number;
  /** 最多采样帧数 */
  max_frames?: number;
  /** 模型精度档 0/1/2 */
  model_complexity?: number;
  /** 子进程超时（秒） */
  timeout?: number;
}): Promise<{
  ok: boolean;
  message?: string;
  frame_count?: number;
  duration?: number;
  fps?: number;
  json_url?: string;
  json_path?: string;
}> {
  const token = bridgeToken();
  const res = await fetch(
    `${BRIDGE}/host/pose-extract?token=${encodeURIComponent(token)}`,
    {
      method: "POST",
      headers: authHeaders(true),
      body: JSON.stringify({
        video: opts.video,
        sample_step: opts.sample_step ?? 1,
        max_frames: opts.max_frames ?? 300,
        model_complexity: opts.model_complexity ?? 1,
        timeout: opts.timeout ?? 180,
      }),
    },
  );
  try {
    return await res.json();
  } catch {
    return { ok: false, message: `HTTP ${res.status}` };
  }
}

/**
 * 白模姿态视频合成（模式 B 第四刀）
 * ---------------------------------
 * 前端逐帧渲染白模姿态并采集 PNG（复用离屏 RenderTarget 读像素，
 * 不依赖 `preserveDrawingBuffer`），把帧序列交给后端 FFmpeg 合成 mp4。
 * 产出的 mp4 即作为 `reference_video` 走第一刀通道。
 *
 * 为什么不在前端实时录制：`MediaRecorder` 录到的是"实时发生"的过程，会掉帧；
 * 逐帧导出则是"要哪帧渲染哪帧"，帧率精确。
 */
export async function poseVideoEncodeViaHost(opts: {
  /** PNG data URL 序列（`data:image/png;base64,...`） */
  frames: string[];
  /** 帧率，默认 25 */
  fps?: number;
  /** 产物名（仅用于文件名，非路径） */
  name?: string;
}): Promise<{
  ok: boolean;
  message?: string;
  url?: string;
  path?: string;
  frames?: number;
  fps?: number;
  duration?: number;
  bytes?: number;
}> {
  const token = bridgeToken();
  const res = await fetch(
    `${BRIDGE}/host/pose-video-encode?token=${encodeURIComponent(token)}`,
    {
      method: "POST",
      headers: authHeaders(true),
      body: JSON.stringify({
        frames: opts.frames,
        fps: opts.fps ?? 25,
        name: opts.name ?? "pose_motion",
      }),
    },
  );
  try {
    return await res.json();
  } catch {
    return { ok: false, message: `HTTP ${res.status}` };
  }
}

// ── 批量视频生成 V2/V3 ──

export type BatchSegment = {
  cameraName: string;
  prompt: string;
  duration: number;
  firstFrame: string;
  lastFrame: string;
  referenceImage?: string;
};

export type BatchCreateResult = {
  ok: boolean;
  job_id?: string;
  total?: number;
  message?: string;
};

export type BatchStatusResult = {
  ok: boolean;
  job_id?: string;
  status?: "running" | "done" | "failed";
  message?: string;
  total?: number;
  done?: number;
  failed?: number;
  concat_status?: string;
  output_path?: string;
  segments?: Array<{
    index: number;
    camera_name: string;
    status: string;
    local_path: string;
    video_url: string;
    error: string;
  }>;
};

export async function batchGenerateVideos(opts: {
  segments: BatchSegment[];
  channel_id: string;
  model: string;
  auto_concat?: boolean;
  transition_sec?: number;
}): Promise<BatchCreateResult> {
  const tok = bridgeToken();
  const body = JSON.stringify({
    segments: opts.segments.map((s) => ({
      cameraName: s.cameraName,
      prompt: s.prompt,
      duration: s.duration,
      firstFrame: s.firstFrame,
      lastFrame: s.lastFrame,
      referenceImage: s.referenceImage || "",
    })),
    channel_id: opts.channel_id,
    model: opts.model,
    auto_concat: !!opts.auto_concat,
    transition_sec: opts.transition_sec || 0,
  });
  try {
    const res = await fetch(`${BRIDGE}/host/video-batch`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Shiguang-Token": tok,
      },
      body,
    });
    const json = await res.json();
    return { ok: true, ...json };
  } catch (e: any) {
    return { ok: false, message: e?.message || String(e) };
  }
}

export async function getBatchStatus(jobId: string): Promise<BatchStatusResult> {
  const tok = bridgeToken();
  try {
    const res = await fetch(`${BRIDGE}/host/video-batch?job_id=${encodeURIComponent(jobId)}`, {
      headers: { "X-Shiguang-Token": tok },
    });
    return await res.json();
  } catch (e: any) {
    return { ok: false, message: e?.message || String(e) };
  }
}

export async function concatVideos(opts: {
  job_id?: string;
  paths?: string[];
  transition_sec?: number;
}): Promise<{ ok: boolean; output_path?: string; video_url?: string; segment_count?: number; total_duration?: number; message?: string }> {
  const tok = bridgeToken();
  const body = JSON.stringify({
    job_id: opts.job_id || "",
    paths: opts.paths || [],
    transition_sec: opts.transition_sec || 0,
  });
  try {
    const res = await fetch(`${BRIDGE}/host/video-concat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Shiguang-Token": tok,
      },
      body,
    });
    return await res.json();
  } catch (e: any) {
    return { ok: false, message: e?.message || String(e) };
  }
}

/** 图 → 静帧视频（成片闭环 · 伪真图卡）。返回本地视频路径数组（供 concatVideos 使用）。 */
export async function imagesToStillVideos(
  items: string[],
  duration?: number,
): Promise<string[]> {
  if (!items.length) return [];
  const tok = bridgeToken();
  try {
    const res = await fetch(`${BRIDGE}/host/still-video`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Shiguang-Token": tok,
      },
      body: JSON.stringify({ items, duration: duration || 3 }),
    });
    const data = await res.json();
    return Array.isArray(data?.paths) ? (data.paths as string[]) : [];
  } catch {
    return [];
  }
}

/** 展开 @角色 / @角色名；并可选自动注入当前角色一致性描述 */
export function expandCharacterMentions(
  text: string,
  prefs: BridgePrefs,
  opts?: { autoInject?: boolean },
): string {
  const name = (prefs.character_name || "").trim();
  const cp = (prefs.character_prompt || "").trim();
  const replacement = cp || (name ? `角色「${name}」` : "");
  let out = text || "";
  if (name && replacement) {
    const esc = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    out = out.replace(new RegExp(`@${esc}`, "g"), replacement);
  }
  out = out.replace(/@角色/g, replacement || "@角色");
  if (opts?.autoInject && replacement && !out.includes(replacement) && !out.includes(`角色「${name}」`)) {
    out = `${replacement}；${out}`;
  }
  return out;
}

export type CanvasAssetRef = {
  id: string;
  title: string;
  kind: string;
  imageUrl?: string;
  promptSnippet?: string;
};

/** 即梦式 @素材 / @节点标题：展开文案，并返回优先参考图 */
export function expandAssetMentions(
  text: string,
  assets: CanvasAssetRef[],
): { text: string; referenceImage?: string } {
  let out = text || "";
  let referenceImage: string | undefined;
  const withImage = assets.filter((a) => a.imageUrl);
  if (/@素材/.test(out) && withImage.length) {
    const a = withImage[withImage.length - 1];
    const rep = a.promptSnippet || `参考素材「${a.title}」`;
    out = out.replace(/@素材/g, rep);
    referenceImage = a.imageUrl;
  }
  for (const a of assets) {
    const title = (a.title || "").trim();
    if (!title) continue;
    const esc = title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const re = new RegExp(`@${esc}`, "g");
    if (re.test(out)) {
      const rep = a.promptSnippet || `参考「${title}」构图与风格`;
      out = out.replace(re, rep);
      if (a.imageUrl) referenceImage = a.imageUrl;
    }
  }
  return { text: out, referenceImage };
}

/** 汇聚指入当前节点的上游脚本/提示词/镜头描述（Comfy 向） */
export function collectUpstreamContext(
  nodeId: string,
  nodes: { id: string; data: any }[],
  edges: { source: string; target: string }[],
): string {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const parts: string[] = [];
  const seen = new Set<string>();
  const queue = edges.filter((e) => e.target === nodeId).map((e) => e.source);
  while (queue.length) {
    const id = queue.shift()!;
    if (seen.has(id)) continue;
    seen.add(id);
    const n = byId.get(id);
    if (!n) continue;
    const d = n.data || {};
    if (d.kind === "script" && d.content) parts.push(`剧本:${String(d.content).slice(0, 200)}`);
    if (d.kind === "prompt" && d.text) parts.push(`风格:${String(d.text).slice(0, 160)}`);
    if (d.kind === "text" && d.content) parts.push(`文本:${String(d.content).slice(0, 160)}`);
    if (d.kind === "config") {
      const cfg = [d.prompt, d.content].filter(Boolean).map(String).join(" ");
      if (cfg) parts.push(`配置:${cfg.slice(0, 120)}`);
    }
    if (d.kind === "shot" && d.prompt) parts.push(`上游镜头:${String(d.prompt).slice(0, 120)}`);
    for (const e of edges) {
      if (e.target === id) queue.push(e.source);
    }
  }
  return parts.join("；");
}

// ── 分镜/拉片族（2026-10-14 拆至 bridgeStoryboard.ts，防本文件顶破规模守卫）──
// 既有 import 路径不变（./bridge 仍可用）；新代码可直接从 ./bridgeStoryboard 导入。
// ⚠️ re-export 而非删除：storyNodes/AgentPages/mediaExtraNodes/novice 等
//    多处 `import { ... } from "./bridge"` 依赖这些符号。
export {
  breakdownStoryboard,
  videoStoryboard,
  referenceBreakdownL2,
  listLocalVisionModels,
  planStoryboardCameras,
  planStoryboardMemory,
  type StoryboardShot,
  type CameraPlanShot,
  type VideoStoryboardShot,
  type ReferenceBreakdownL2Shot,
  type MemoryPlanRow,
} from "./bridgeStoryboard";

export function readFileAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result || ""));
    r.onerror = () => reject(r.error);
    r.readAsDataURL(file);
  });
}

/** 上传参考视频/图到宿主 inbox，返回可播放 URL（大文件勿走 dataURL） */
export async function uploadAssetToHost(file: File): Promise<{
  ok: boolean;
  url?: string;
  path?: string;
  kind?: string;
  message?: string;
}> {
  const token = bridgeToken();
  const q = new URLSearchParams({
    token,
    filename: file.name || "asset.bin",
  });
  try {
    const res = await fetch(`${BRIDGE}/host/upload-asset?${q.toString()}`, {
      method: "POST",
      headers: {
        ...authHeaders(false),
        "Content-Type": file.type || "application/octet-stream",
      },
      body: file,
    });
    return await res.json();
  } catch (e) {
    return { ok: false, message: `上传失败: ${e}` };
  }
}

/** 画布捏脸卡片 → 角色库写回（唯一写回通道 POST /host/character-update）。
 *  后端只接受 CHARACTER_FIELD_SCHEMA 白名单字段 + avatar_url，传其它键会被静默忽略。 */
export async function updateCharacterViaHost(
  id: string,
  data: Record<string, unknown>,
): Promise<{ ok: boolean; message?: string }> {
  try {
    const res = await fetch(`${BRIDGE}/host/character-update`, {
      method: "POST",
      headers: authHeaders(true),
      body: JSON.stringify({ id, data }),
    });
    return await res.json();
  } catch (e) {
    return { ok: false, message: `写回角色库失败: ${e}` };
  }
}

/** 捏脸 AI 生成（POST /host/face-template/generate）：提示词 → FaceParams 结构，不落库。
 *  后端未配置模型 / 输出不可解析时返回 ok:false + 明确 message（诚实失败，不造假参数）。 */
export async function generateFaceTemplateViaHost(
  prompt: string,
  base?: Record<string, unknown> | null,
): Promise<{ ok: boolean; params?: unknown; message?: string; dropped?: string[] }> {
  try {
    const res = await fetch(`${BRIDGE}/host/face-template/generate`, {
      method: "POST",
      headers: authHeaders(true),
      body: JSON.stringify({ prompt, base: base ?? null }),
    });
    return await res.json();
  } catch (e) {
    return { ok: false, message: `生成接口不可用: ${e}` };
  }
}

const persistInflight = new Map<string, Promise<string>>();

function mimeToExt(mime: string): string {
  if (mime.includes("png")) return "png";
  if (mime.includes("jpeg") || mime.includes("jpg")) return "jpg";
  if (mime.includes("webp")) return "webp";
  if (mime.includes("gif")) return "gif";
  if (mime.includes("mp4")) return "mp4";
  if (mime.includes("webm")) return "webm";
  if (mime.includes("wav")) return "wav";
  if (mime.includes("mpeg") || mime.includes("mp3")) return "mp3";
  return "bin";
}

/** dataURL → 宿主 inbox URL；非 data / 过小 / 上传失败则原样返回 */
export async function persistMediaUrl(url: string): Promise<string> {
  if (!url || typeof url !== "string") return url;
  if (!url.startsWith("data:") || url.length < 4096) return url;
  const hit = persistInflight.get(url);
  if (hit) return hit;
  const job = (async () => {
    try {
      const blob = await dataUrlToBlob(url);
      const ext = mimeToExt(blob.type || "");
      const file = new File(
        [blob],
        `canvas_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}.${ext}`,
        { type: blob.type || "application/octet-stream" },
      );
      const up = await uploadAssetToHost(file);
      if (up.ok && up.url) return up.url;
    } catch {
      /* 桥不可用时保留 dataURL */
    }
    return url;
  })().finally(() => {
    persistInflight.delete(url);
  });
  persistInflight.set(url, job);
  return job;
}

/** 优先宿主落盘；失败时回退 dataURL（仅小文件） */
export async function resolveMediaUrl(file: File, maxDataUrlBytes = 8_000_000): Promise<{
  ok: boolean;
  url: string;
  via: "host" | "dataurl";
  message?: string;
}> {
  const up = await uploadAssetToHost(file);
  if (up.ok && up.url) {
    return { ok: true, url: up.url, via: "host", message: up.message };
  }
  if (file.size > maxDataUrlBytes) {
    return {
      ok: false,
      url: "",
      via: "dataurl",
      message: up.message || "文件过大且宿主上传失败，请确认画布桥已启动",
    };
  }
  const url = await readFileAsDataUrl(file);
  return { ok: true, url, via: "dataurl", message: "已用本地 dataURL（桥不可用）" };
}

export async function syncModelPool(): Promise<string> {
  const token = bridgeToken();
  try {
    const res = await fetch(
      `${BRIDGE}/host/ai-config-patch?token=${encodeURIComponent(token)}`,
      { headers: authHeaders() },
    );
    const data = await res.json();
    if (!data.ok || !data.channels) return "同步失败：桥未就绪或无渠道";
    const raw = localStorage.getItem(CONFIG_KEY);
    const store = raw
      ? JSON.parse(raw)
      : { state: { config: { channels: [] } }, version: 0 };
    if (!store.state) store.state = {};
    if (!store.state.config) store.state.config = {};
    let channels = Array.isArray(store.state.config.channels)
      ? store.state.config.channels.slice()
      : [];
    data.channels.forEach((ch: any) => {
      const idx = channels.findIndex((c: any) => c && c.id === ch.id);
      if (idx >= 0) channels[idx] = Object.assign({}, channels[idx], ch);
      else channels.push(ch);
    });
    store.state.config.channels = channels;
    store.state.config.channelMode = "local";
    if (data.defaults) {
      Object.keys(data.defaults).forEach((k) => {
        if (data.defaults[k]) store.state.config[k] = data.defaults[k];
      });
    }
    localStorage.setItem(CONFIG_KEY, JSON.stringify(store));
    localStorage.setItem("__shiguang_models_synced_v1", "1");
    localStorage.setItem("__shiguang_aigc_synced_v1", "1");
    const warns = (data.warnings || []) as string[];
    const base = `已同步 ${data.channels.length} 个渠道（激活：${data.active_provider_label || data.active_provider || "无"}）`;
    if (warns.length) return `${base}。注意：${warns[0]}`;
    if (!data.has_image_models) {
      return `${base}。尚无可用生图模型，请在模型管理为硅基流动等填写 Key。`;
    }
    return base;
  } catch (e) {
    return `同步异常: ${e}`;
  }
}

export type AgentStatus = {
  ok: boolean;
  url?: string;
  token?: string;
  listening?: boolean;
  message?: string;
};

export function applyAgentCredentials(url: string, token: string) {
  if (!url || !token) return;
  localStorage.setItem("canvas-agent-url", url);
  localStorage.setItem("canvas-agent-token", token);
  (window as any).__SHIGUANG_AGENT_URL = url;
  (window as any).__SHIGUANG_AGENT_TOKEN = token;
}

export async function getAgentStatus(): Promise<AgentStatus> {
  const token = bridgeToken();
  try {
    const res = await fetch(
      `${BRIDGE}/host/agent?token=${encodeURIComponent(token)}`,
      { headers: authHeaders() },
    );
    const data = await res.json();
    return {
      ok: Boolean(data.ok),
      url: data.url,
      token: data.token,
      listening: Boolean(data.listening),
      message: data.message,
    };
  } catch (e) {
    return { ok: false, message: `无法查询 Agent: ${e}` };
  }
}

/** 启动宿主 canvas-agent 并写入本地凭证（可从画布配置页调用） */
export async function startCanvasAgent(): Promise<AgentStatus> {
  const token = bridgeToken();
  try {
    const res = await fetch(
      `${BRIDGE}/host/agent/start?token=${encodeURIComponent(token)}`,
      { method: "POST", headers: authHeaders(true), body: "{}" },
    );
    const data = await res.json();
    if (data.ok && data.token) {
      applyAgentCredentials(String(data.url || ""), String(data.token));
    }
    return {
      ok: Boolean(data.ok),
      url: data.url,
      token: data.token,
      listening: Boolean(data.listening),
      message: data.message,
    };
  } catch (e) {
    return { ok: false, message: `启动 Agent 异常: ${e}` };
  }
}

export function installInjectScript() {
  if (document.getElementById("shiguang-bridge-inject")) return;
  const s = document.createElement("script");
  s.id = "shiguang-bridge-inject";
  s.src = `${BRIDGE}/inject.js?t=${Date.now()}`;
  s.async = true;
  document.documentElement.appendChild(s);
}

export async function sendBlobToEditor(
  blob: Blob,
  filename: string,
  prefs: BridgePrefs,
  opts?: {
    duration_sec?: number;
    title?: string;
    node_id?: string;
    kind?: string;
    /** 生成参数血缘块（prompt/model/seed/character_id…缺键不发） */
    generation?: Record<string, string | number>;
  },
): Promise<string> {
  const q = new URLSearchParams({
    filename,
    title: opts?.title || filename,
    send_to_editor: "1",
    enable_interpolation: prefs.enable_interpolation ? "1" : "0",
    character_id: prefs.character_id || "",
    character_name: prefs.character_name || "",
  });
  if (opts?.duration_sec && opts.duration_sec > 0) {
    q.set("duration_sec", String(opts.duration_sec));
  }
  if (opts?.node_id) q.set("node_id", opts.node_id);
  if (opts?.kind) q.set("kind", opts.kind);
  // 血缘块非空才发；后端 _handle_ingest 解析 generation_json 透传入轨载荷
  if (opts?.generation && Object.keys(opts.generation).length) {
    q.set("generation_json", JSON.stringify(opts.generation));
  }
  const res = await fetch(`${BRIDGE}/ingest?${q}`, {
    method: "POST",
    body: blob,
    headers: { "Content-Type": blob.type || "application/octet-stream" },
  });
  const data = await res.json();
  return data.message || (data.success ? "已发送到剪辑" : "发送失败");
}

export type EditorOutboxItem = {
  id: string;
  title?: string;
  filename?: string;
  ext?: string;
  url: string;
  clip_id?: string;
  canvas_node_id?: string;
  kind?: string;
  in_point?: number;
  out_point?: number;
  start_time?: number;
  duration?: number;
};

export async function fetchEditorOutbox(): Promise<EditorOutboxItem[]> {
  try {
    const res = await fetch(`${BRIDGE}/editor_outbox`);
    const data = await res.json();
    return Array.isArray(data?.items) ? data.items : [];
  } catch {
    return [];
  }
}

export type TimelineSnapshotClip = {
  id?: string;
  name?: string;
  path?: string;
  type?: string;
  start_time?: number;
  duration?: number;
  end_time?: number;
  canvas_node_id?: string;
  canvas_kind?: string;
};

export type TimelineSnapshot = {
  ok?: boolean;
  clip_count?: number;
  clips?: TimelineSnapshotClip[];
  gaps?: unknown[];
  suggestions?: unknown[];
  message?: string;
};

export async function fetchTimelineSnapshot(): Promise<TimelineSnapshot> {
  const token = bridgeToken();
  try {
    const res = await fetch(
      `${BRIDGE}/host/timeline-snapshot?token=${encodeURIComponent(token)}`,
      { headers: authHeaders() },
    );
    return await res.json();
  } catch {
    return { ok: false, clips: [], clip_count: 0 };
  }
}

export async function dataUrlToBlob(dataUrl: string): Promise<Blob> {
  const res = await fetch(dataUrl);
  return await res.blob();
}

export function placeholderImageDataUrl(prompt: string, w = 512, h = 288): string {
  /* M0.4 生图失败不再写入此占位图；保留函数以免旧调用方编译失败 */
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  const ctx = c.getContext("2d")!;
  const g = ctx.createLinearGradient(0, 0, w, h);
  g.addColorStop(0, "#1e3a5f");
  g.addColorStop(1, "#0f766e");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, w, h);
  ctx.fillStyle = "rgba(255,255,255,0.92)";
  ctx.font = "bold 18px sans-serif";
  ctx.fillText("拾光导演台 · 占位图", 24, 40);
  ctx.font = "14px sans-serif";
  const lines = wrapText(prompt || "(空提示词)", 28);
  lines.slice(0, 8).forEach((line, i) => ctx.fillText(line, 24, 80 + i * 22));
  ctx.fillStyle = "rgba(255,255,255,0.55)";
  ctx.font = "11px sans-serif";
  ctx.fillText("同步模型池并配置 AIGC Key 后可接真实生图", 24, h - 24);
  return c.toDataURL("image/png");
}

// ────────────────────────────────────────────────────────────────────
// Agent ↔ Canvas 双向通信（SSE 接收 + POST 回执）
// ────────────────────────────────────────────────────────────────────

// SSE 订阅已按模块规模守卫（2026-10-14）拆到 agentEvents.ts；此处保留再导出，
// 调用方（AgentPanel 等）仍从 "./bridge" 取用，无需改导入路径。
export { subscribeAgentEvents, type AgentEventEnvelope } from "./agentEvents";

/**
 * 画布侧主动给剪辑侧发一条事件（对 task.create 的回执 / canvas.query / canvas.node_added 等）。
 */
export async function sendAgentReply(opts: {
  correlation_id?: string;
  type?: string;
  payload: any;
}): Promise<{ ok: boolean; message?: string; id?: string }> {
  const token = bridgeToken();
  try {
    const res = await fetch(`${BRIDGE}/host/agent/reply?token=${encodeURIComponent(token)}`, {
      method: "POST",
      headers: authHeaders(true),
      body: JSON.stringify({
        correlation_id: opts.correlation_id || "",
        type: opts.type || "canvas.reply",
        payload: opts.payload,
      }),
    });
    const data = await res.json();
    return {
      ok: Boolean(data.ok),
      message: data.message,
      id: data.id,
    };
  } catch (e: any) {
    return { ok: false, message: `回执失败: ${e?.message || e}` };
  }
}

function wrapText(text: string, maxChars: number): string[] {
  const out: string[] = [];
  let cur = "";
  for (const ch of text) {
    cur += ch;
    if (cur.length >= maxChars) {
      out.push(cur);
      cur = "";
    }
  }
  if (cur) out.push(cur);
  return out;
}
