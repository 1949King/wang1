/** 与拾光剪影 canvas_bridge (:18765) 对接 */

export const BRIDGE = "http://127.0.0.1:18765";
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

export async function generateImageViaHost(opts: {
  prompt: string;
  model?: string;
  channel_id?: string;
  size?: string;
  reference_image?: string;
  strength?: number;
  n?: number;
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
        }),
      },
    );
    try {
      return await res.json();
    } catch {
      return { ok: false, message: `HTTP ${res.status}`, fallback_placeholder: true };
    }
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
  first_frame?: string;
  last_frame?: string;
}): Promise<{
  ok: boolean;
  message?: string;
  video_url?: string;
  video_path?: string;
  model?: string;
  channel_id?: string;
  channel_name?: string;
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
        first_frame: opts.first_frame || "",
        last_frame: opts.last_frame || "",
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
  opts?: { duration_sec?: number; title?: string },
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
  const res = await fetch(`${BRIDGE}/ingest?${q}`, {
    method: "POST",
    body: blob,
    headers: { "Content-Type": blob.type || "application/octet-stream" },
  });
  const data = await res.json();
  return data.message || (data.success ? "已发送到剪辑" : "发送失败");
}

export async function dataUrlToBlob(dataUrl: string): Promise<Blob> {
  const res = await fetch(dataUrl);
  return await res.blob();
}

export function placeholderImageDataUrl(prompt: string, w = 512, h = 288): string {
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
