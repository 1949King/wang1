/** 与拾光剪影 canvas_bridge (:18765) 对接 */

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
  return (
    (window as any).__SHIGUANG_BRIDGE_TOKEN ||
    localStorage.getItem("__shiguang_bridge_token") ||
    tokenFromQuery() ||
    ""
  );
}

function authHeaders(json = false): HeadersInit {
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
  reference_image?: string;
  strength?: number;
  n?: number;
  quality?: string;
  /** 人脸修复模型后台预载进度回调（GFPGAN 下载期间异步上报，不阻塞生图返回） */
  onPreloadProgress?: (p: { progress: number; message: string }) => void;
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
  /** 画质档含人脸修复时后端自动触发的 GFPGAN 后台预载任务 id（据此轮询 /host/model-preload） */
  preload_job_id?: string;
  /** 触发时人脸修复模型是否已就绪（true=可走 GFPGAN，false=本次暂时回退区域超分） */
  face_restore_ready?: boolean;
}> {
  const token = bridgeToken();
  const count = Math.max(1, Math.min(4, opts.n || 1));
  if (count === 1) {
    const res = await fetch(
      `${BRIDGE}/host/generate-image?token=${encodeURIComponent(token)}`,
      {
        method: "POST",
        headers: authHeaders(true),
        body: JSON.stringify({
          prompt: opts.prompt,
          model: opts.model || "",
          channel_id: opts.channel_id || "",
          size: opts.size || "1024x576",
          reference_image: opts.reference_image || "",
          strength: opts.strength ?? 0.65,
          quality: opts.quality || "standard",
        }),
      },
    );
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
      preload_job_id?: string;
      face_restore_ready?: boolean;
    };
    try {
      data = await res.json();
    } catch {
      return { ok: false, message: `HTTP ${res.status}`, fallback_placeholder: true };
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
  let lastMsg = "";
  let okAny = false;
  for (let i = 0; i < count; i++) {
    const one = await generateImageViaHost({ ...opts, n: 1 });
    lastMsg = one.message || lastMsg;
    const url = one.image_data_url || one.image_url;
    if (one.ok && url) {
      images.push(url);
      okAny = true;
    }
  }
  return {
    ok: okAny,
    images,
    image_data_url: images[0],
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
          size: opts.size || "1024x576",
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
  const token = bridgeToken();
  const res = await fetch(
    `${BRIDGE}/host/generate-video?token=${encodeURIComponent(token)}`,
    {
      method: "POST",
      headers: authHeaders(true),
      body: JSON.stringify({
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
      }),
    },
  );
  try {
    return await res.json();
  } catch {
    return { ok: false, message: `HTTP ${res.status}` };
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

export type StoryboardShot = {
  id?: number;
  duration?: number;
  shot?: string;
  description?: string;
  dialogue?: string;
};

/** 一键拉片：剧本 → 分镜表（宿主 LLM，失败用启发式） */
export async function breakdownStoryboard(script: string): Promise<{
  ok: boolean;
  shots: StoryboardShot[];
  fallback?: boolean;
  message?: string;
}> {
  const token = bridgeToken();
  const res = await fetch(
    `${BRIDGE}/host/storyboard-breakdown?token=${encodeURIComponent(token)}`,
    {
      method: "POST",
      headers: authHeaders(true),
      body: JSON.stringify({ script }),
    },
  );
  try {
    return await res.json();
  } catch {
    return { ok: false, shots: [], message: `HTTP ${res.status}` };
  }
}

/** 相机路径规划结果：镜像后端 StageCamera 结构 + 运镜 pathPoints */
export type CameraPlanShot = {
  id: string;
  name: string;
  position: [number, number, number];
  lookAt: [number, number, number];
  fov: number;
  shotSize?: string;
  movement?: string;
  pathPoints?: { pos: [number, number, number]; look: [number, number, number] }[];
  pathDuration?: number;
};

/** 一键拉片（视频）单镜：镜像后端 /host/video-storyboard 的 shots 行 */
export type VideoStoryboardShot = {
  id?: number;
  start?: number;
  end?: number;
  duration?: number;
  shot?: string;
  camera?: string;
  description?: string;
  dialogue?: string;
  tone?: string;
  brightness?: number;
  frame?: string | null;
};

/** 一键拉片：参考视频 → 可编辑分镜表（后端检测镜头边界 + 抽帧 + 色调/景别） */
export async function videoStoryboard(input: {
  path?: string;
  url?: string;
  max_shots?: number;
}): Promise<{
  ok: boolean;
  shots: VideoStoryboardShot[];
  fallback?: boolean;
  scene_source?: string;
  duration?: number;
  message?: string;
}> {
  const token = bridgeToken();
  try {
    const res = await fetch(
      `${BRIDGE}/host/video-storyboard?token=${encodeURIComponent(token)}`,
      {
        method: "POST",
        headers: authHeaders(true),
        body: JSON.stringify({
          path: input.path || "",
          url: input.url || "",
          max_shots: input.max_shots || 30,
        }),
      },
    );
    return await res.json();
  } catch {
    return { ok: false, shots: [], message: "网络异常" };
  }
}

/** WS4#2 AI 分镜自动摆机位：分镜表 / 剧本 → 相机路径规划（经画布桥） */
export async function planStoryboardCameras(input: {
  shots?: StoryboardShot[];
  script?: string;
  use_llm?: boolean;
}): Promise<{
  ok: boolean;
  cameras: CameraPlanShot[];
  count?: number;
  message?: string;
}> {
  const token = bridgeToken();
  try {
    const res = await fetch(
      `${BRIDGE}/host/storyboard-camera-plan?token=${encodeURIComponent(token)}`,
      {
        method: "POST",
        headers: authHeaders(true),
        body: JSON.stringify({
          shots: input.shots,
          script: input.script || "",
          use_llm: input.use_llm || false,
        }),
      },
    );
    return await res.json();
  } catch {
    return { ok: false, cameras: [], message: "网络异常" };
  }
}

/** 记忆规划单行：镜像后端 app/core/ai/storyboard_memory.plan 的返回 */
export type MemoryPlanRow = {
  id: string;
  memoryType: "detail" | "meaning" | "emotion";
  label: string;
  /** t 小时后的基线保留率 0~1（后端按 memory_model 的 λ 算，前端不要自己算） */
  retention: number;
  currentDuration: number;
  suggestedDuration: number;
  delta: number;
};

/**
 * 分镜记忆规划：给定每镜的「观众记忆类型」，换算保留率与建议时长。
 *
 * 总时长守恒、按保留率加权再分配 —— 细节让位、情绪拿时长。
 * 理论依据：24h 基线保留率 细节 11.5% / 意义 61.9% / 情绪 82.5%。
 *
 * ⚠️ 保留率与分配一律由后端算（λ 的唯一真相源在 Python 侧），
 *    前端只负责选类型 + 展示回传的真值，避免两份 λ 漂移。
 */
export async function planStoryboardMemory(input: {
  rows: { id: string; memoryType?: string; duration?: number }[];
  t_hours?: number;
}): Promise<{
  ok: boolean;
  t_hours?: number;
  rows: MemoryPlanRow[];
  totalCurrent?: number;
  totalSuggested?: number;
  warnings?: string[];
  message?: string;
}> {
  const token = bridgeToken();
  try {
    const res = await fetch(
      `${BRIDGE}/host/storyboard-memory-plan?token=${encodeURIComponent(token)}`,
      {
        method: "POST",
        headers: authHeaders(true),
        body: JSON.stringify({
          rows: input.rows,
          ...(input.t_hours ? { t_hours: input.t_hours } : {}),
        }),
      },
    );
    return await res.json();
  } catch {
    return { ok: false, rows: [], message: "网络异常" };
  }
}

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
  opts?: { duration_sec?: number; title?: string; node_id?: string; kind?: string },
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

export type AgentEventEnvelope = {
  id: string;
  ts: number;
  from: string;
  to: string;
  type: string;
  correlation_id: string;
  payload: any;
  ack_required: boolean;
};

type SubscribeOpts = {
  onEvent: (evt: AgentEventEnvelope) => void;
  onError?: (err: string) => void;
  sinceId?: string;
};

/**
 * 订阅剪辑 Agent 推过来的 SSE 事件（/host/agent/events）。
 * 浏览器 EventSource 自带断线自动重连。
 * 返回一个取消订阅函数（调 es.close()）。
 */
export function subscribeAgentEvents(opts: SubscribeOpts): () => void {
  const token = bridgeToken();
  const params = new URLSearchParams({ token });
  if (opts.sinceId) params.set("since_id", opts.sinceId);
  const url = `${BRIDGE}/host/agent/events?${params.toString()}`;

  let es: EventSource | null = null;
  try {
    es = new EventSource(url);
  } catch (e: any) {
    opts.onError?.(`SSE 创建失败: ${e?.message || e}`);
    return () => {};
  }

  let lastId = opts.sinceId || "";
  es.addEventListener("agent", (ev) => {
    const msg = ev as MessageEvent;
    try {
      const data = JSON.parse(String(msg.data || "{}"));
      const env: AgentEventEnvelope = {
        id: String(data.id || ""),
        ts: Number(data.ts || 0),
        from: String(data.from || ""),
        to: String(data.to || ""),
        type: String(data.type || ""),
        correlation_id: String(data.correlation_id || ""),
        payload: data.payload,
        ack_required: Boolean(data.ack_required),
      };
      if (env.id) lastId = env.id;
      opts.onEvent(env);
    } catch (e: any) {
      opts.onError?.(`SSE 消息解析失败: ${e?.message || e}`);
    }
  });

  es.onerror = () => {
    // EventSource 会自动重连，这里只做日志
    opts.onError?.("SSE 连接异常（正在自动重连）");
  };

  return () => {
    try {
      es?.close();
    } catch {
      /* ignore */
    }
  };
}

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
